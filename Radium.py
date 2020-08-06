import os
import random
import threading
import time
import re
from collections import namedtuple
from typing import List, Tuple

import keyboard
import osascript
import vlc

from RadiumStatusIcon import RadiumStatusIcon
from StringSearch import makeSearchable, searchableChars, stringSearch

Folder = namedtuple("Folder", ["name", "searchableName", "subFolders", "songs", "macros"])
Macro = namedtuple("Macro", ["name", "searchableName", "localPath"])
Song = namedtuple("Song", ["name", "searchableName", "localPath"])


def msToStr(ms):
    ms //= 1000
    if(ms >= 3600):
        return f"{ms//3600:02d}:{(ms//60)%60:02d}:{ms%60:02d}"
    else:
        return f"{(ms//60)%60:02d}:{ms%60:02d}"


class Radium:
    def __init__(self):
        self.versionStr = "2.0"
        self.audioDirectory: str = None

        self.searchScriptPath: str = None
        self.searchResultPath: str = None

        self.searchThread = None

        self.ctrlDown = False
        self.shiftDown = False
        
        self.keybinds = dict()
        self.acceptedAudioTypes = None
        self.maxHistoryStackSize: int = 30
        self.folderSearchLimit = 5
        self.macroCallLimit = 10

        self.folders: List[Folder] = list()
        self.macros: List[Macro] = list()
        self.songs: List[Song] = list()

        self.activeSongs: Set[Song] = set()
        self.songQueue: List[Song] = list()
        self.historyStack: List[Tuple(Song, int)] = list()

        self.vlcInst = None
        self.player = None
        self.statusIcon = None

        self.loopingActive = False
        self.autoplayActive = True
        self.volume = 100
        self.playing = False
        self.currentSong = None
        self.currentTime = 1
        
        self.songStartThread = None
        self.prevKeyHook = None

        self.queuedStatusIconTasks = list()
        self.statusIconQueueLock = threading.Lock()
        self.statusIconQueueThread = None

    def onSongChanged(self):
        self.setButtonTitle("song", f"Playing: \"{self.currentSong.name}\"")

    def onTimeChanged(self):
        # player.get_time() will often wrongly be 0, 
        # and will pretty much never correctly be 0
        # so, if it's 0, just use the previous time instead
        self.currentTime = self.player.get_time() or self.currentTime

    def onLengthChanged(self):
        self.currentSongLength = self.player.get_length()
        self.setButtonTitle("songLength", f"Length: {msToStr(self.currentSongLength)}")

    def setSong(self, song, addToHistory=True):
        # add existing song to history stack
        if(self.currentSong):
            if(addToHistory and (len(self.historyStack) == 0 or self.historyStack[-1][0] != song)):
                prevTime = self.currentTime
                if(prevTime < 5000 or prevTime > self.currentSongLength - 5000):
                    prevTime = 1

                self.historyStack.append((self.currentSong, prevTime))

            if(len(self.historyStack) >= self.maxHistoryStackSize):
                self.historyStack.pop(0)
        
        
        self.setupVLC()

        self.currentTime = 1
        self.currentSong = song
        self.currentSongUpdated()

        path = os.path.join(self.audioDirectory, song.localPath)
        self.player.set_media(self.vlcInst.media_new_path(path))
    
    def currentSongUpdated(self):
        self.setButtonTitle("song", f"----")
        self.setButtonTitle("songLength", f"----")

    def doSearch(self):
        # self._handleSearch()
        if(self.searchThread == None):
            self.searchThread = threading.Thread(
                target=self._handleSearch, daemon=True)
            self.searchThread.start()

    def _handleSearch(self):
        result = self.openSearchScript()
        self.searchThread = None
        if(result):
            self.processSearchEntry(result)

    def searchFolders(self, parts, root):
        subFolderSNs = [sub.searchableName for sub in root.subFolders]
        # if only 1 term, find the corresponding folder
        if(len(parts) == 1):
            founds = stringSearch(parts[0], subFolderSNs, 1)
            if(founds):
                return self.folders[founds[0]]
            return None

        founds = stringSearch(parts[0], subFolderSNs, self.folderSearchLimit)
        for candidateFolderIndex in founds:
            result = self.searchFolders(
                parts[1:], self.folders[candidateFolderIndex])
            if(result):
                return result
        return None

    def getAllSongsInFolder(self, folder):
        songs = list()
        songs.extend(folder.songs)
        for sub in folder.subFolders:
            songs.extend(self.getAllSongsInFolder(sub))
        return songs

    def getAllMacrosInFolder(self, folder):
        macros = list()
        macros.extend(folder.macros)
        for sub in folder.subFolders:
            macros.extend(self.getAllMacrosInFolder(sub))
        return macros

    def resolveMacros(self, entry):
        macroCount = 0
        while True:
            if(macroCount > self.macroCallLimit):
                return None

            found = re.search(r">([a-z \/]+)", entry)
            if(not found):
                break
            macroCount += 1

            macroPool = self.macros
            
            term = found.group(1).strip().lower()
            pathParts = list(filter(len, term.split("/")))
            
            # macro has no folder mode: pretend that trailing /'s aren't there
            if(len(pathParts) > 1):
                folder = self.searchFolders(pathParts[:-1], self.omnifolder)
                if(folder):
                    macroPool = self.getAllMacrosInFolder(folder)
                else:
                    return None
            
            macroPool.sort(key=lambda mac : len(mac.searchableName))
            folderMacroSNs = list(mac.searchableName for mac in macroPool)
            foundIndices = stringSearch(pathParts[-1], folderMacroSNs, 1)
            if(len(foundIndices) == 0):
                return None

            macroContents = self.readMacroFile(self.macros[foundIndices[0]].localPath)
            if(macroContents == None):
                return None

            entry = entry[:found.start()] + macroContents + entry[found.end():]
        return entry

    def processSearchEntry(self, entry):
        entry = entry.strip().lower()
        entry = self.resolveMacros(entry)
        if(not entry):
            return

        cmds = filter(len, (cmd.strip() for cmd in entry.split(";")))
        for cmd in cmds:
            self.processSearchCommand(cmd)

    def processSearchCommand(self, cmd):
        # lone commands
        if cmd == "@":
            self.activeSongs = set()
            self.activeSongsUpdated()
            return
        if cmd == "?":
            random.shuffle(self.songQueue)
            return

        split = 0
        for i in range(len(cmd)):
            if cmd[i] in searchableChars or cmd[i] == "/":
                split = i
                break

        modifiers = cmd[:split]
        search = cmd[split:]

        allSelectedSongs = []

        terms = filter(len, (term.strip() for term in search.split(",")))
        for term in terms:
            allSelectedSongs.extend(self.processSearchTerm(term))

        if(len(allSelectedSongs) == 0):
            return

        if "@" in modifiers:  # active mode
            if "+" in modifiers:
                self.activeSongs += allSelectedSongs
            elif "-" in modifiers:
                self.activeSongs -= allSelectedSongs
            elif "*" in modifiers:
                self.activeSongs &= allSelectedSongs
            else:
                self.activeSongs = set(allSelectedSongs)
            self.activeSongsUpdated()
        else:  # queue mode
            if "?" in modifiers:
                random.shuffle(allSelectedSongs)

            if "+" in modifiers:
                self.songQueue.extend(allSelectedSongs)
            else:
                self.songQueue = allSelectedSongs + self.songQueue
            self.songQueueUpdated()

    def processSearchTerm(self, term):
        songPool = self.songs

        pathParts = list(filter(len, term.split("/")))

        wholeFolder = term[0] == "/" or term[-1] == "/"

        # if /'s are present, find a folder
        if(wholeFolder or len(pathParts) > 1):
            folderParts = pathParts if wholeFolder else pathParts[:-1]
            folder = self.searchFolders(folderParts, self.omnifolder)

            if(folder):
                songPool = self.getAllSongsInFolder(folder)
            else:
                return []

        if wholeFolder:
            return songPool
        else:
            songPool.sort(key=lambda song : len(song.searchableName))
            # single song mode
            folderSongSNs = list(song.searchableName for song in songPool)
            foundIndices = stringSearch(pathParts[-1], folderSongSNs, 1)
            return [songPool[i] for i in foundIndices]

    def openSearchScript(self):
        ret, result, err = osascript.run("return display dialog \"\" default answer \"\"")
        if(ret):
            return None

        entry = result.split(":")[2]
        if(len(entry.strip()) == 0):
            return None
        return entry

    def togglePlaying(self):
        if(self.playing):
            self.pausePlaying()
        else:
            self.startPlaying()
    
    def startPlaying(self, seekTime = -1):
        self.songStartThread = threading.Thread(target=lambda : self._startPlaying(seekTime=seekTime), daemon=True)
        self.songStartThread.start()
        self.songStartThread.join()
        self.songStartThread = None

    def _startPlaying(self, seekTime = -1):
        self.playing = True
        self.player.play()
        if(seekTime >= 0):
            try:
                self.currentTime = seekTime
                self.player.set_time(seekTime)
            except:
                pass
        elif(self.isEnded()):
            self.player.set_time(1)
            self.currentTime = 1
            
        self.player.set_pause(False)
        self.playingUpdated()

    def pausePlaying(self):
        self.playing = False
        self.player.set_pause(True)
        self.playingUpdated()

    def playingUpdated(self):
        self.setButtonTitle("pause", "Playing" if self.playing else "Paused")

    def setLooping(self, newState):
        self.loopingActive = newState
        self.setButtonState("loop", self.loopingActive)

    def toggleLooping(self):
        self.setLooping(not self.loopingActive)

    def setAutoplay(self, newState):
        self.autoplayActive = newState
        self.setButtonState("autoplay", self.autoplayActive)

    def toggleAutoplay(self):
        self.setAutoplay(not self.autoplayActive)

    def songQueueUpdated(self):
        self.setButtonTitle(
            "clearQueue", f"Queue Size: {len(self.songQueue)}")

    def activeSongsUpdated(self):
        self.setButtonTitle("activeSongs", f"Active Songs: {len(self.activeSongs) or len(self.songs)}")

    def clearQueue(self):
        self.songQueue.clear()
        self.songQueueUpdated()

    def songQueuePop(self, index):
        item = self.songQueue.pop(index)
        self.songQueueUpdated()
        return item

    # def _onStatusIconStart(self):
    #     self.statusIconQueueLock.acquire()
    #     for task in self.queuedStatusIconTasks:
    #         print(task)
    #         task()
    #     self.queuedStatusIconTasks.clear()
    #     self.statusIconQueueLock.release()

    def queueStatusIconTask(self, task):
        if(self.statusIcon):
            task()
        # else:
        #     while not self.statusIcon:
        #         time.sleep(0.1)

        #     self.statusIconQueueLock.acquire()
        #     self.queuedStatusIconTasks.append(task)
        #     self.statusIconQueueLock.release()
        #     if(self.statusIconQueueThread):
        #         self.statusIconQueueThread.join()
            # self.statusIconQueueThread = threading.Thread(target=self._awaitStatusIconStart, daemon=True)
        #     self.statusIconQueueThread.start()
            

    # def _awaitStatusIconStart(self):
    #     while not self.statusIcon:
    #         time.sleep(0.1)
    #         print("wait")
    #     self._onStatusIconStart()
        
    def run(self):
        self.reboot()
        self.startStatusIcon()

    def reboot(self):
        try:
            self.loadConfig()
            self.loadSongList()
            self.setupKeybinds()
            self.setupVLC()
        except BaseException as excep:
            print(excep)
        
    def setupVLC(self):
        if(self.player):
            self.player.release()
        if(self.vlcInst):
            self.vlcInst.release()

        self.vlcInst = vlc.Instance()
        self.player = self.vlcInst.media_player_new()
        self.player.audio_set_volume(self.volume)
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, lambda e : self.onSongEnd())
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerTimeChanged, lambda e : self.onTimeChanged())
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerLengthChanged, lambda e : self.onLengthChanged())
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerMediaChanged, lambda e : self.onSongChanged())

    def startStatusIcon(self):
        if(self.statusIcon):
            self.statusIcon.kill()
        self.statusIcon = RadiumStatusIcon(self)
        self.statusIcon.run()

    def setNext(self):
        if(len(self.songQueue)):
            self.setSong(self.songQueuePop(0))
        else:
            candidateSongs = self.songs
            if(self.activeSongs):
                candidateSongs = list(self.activeSongs)

            self.setSong(random.choice(candidateSongs))

    def playNext(self):
        self.setNext()
        self.startPlaying()

    # don't bother trying to split into setPrev/playPrev; it screws things up
    def playPrev(self):
        if(self.historyStack):
            stakItem = self.historyStack.pop()
            self.setSong(stakItem[0], addToHistory=False)
            self.startPlaying(seekTime=stakItem[1])

    def _setButtonTitle(self, button, title):
        self.statusIcon.buttons[button].title = title

    def setButtonTitle(self, button, title):
        self.queueStatusIconTask(lambda:self._setButtonTitle(button, title))

    def _setButtonState(self, button, state):
        self.statusIcon.buttons[button].state = state

    def setButtonState(self, button, state):
        self.queueStatusIconTask(lambda:self._setButtonState(button, state))

    def getVolume(self):
        return self.player.audio_get_volume()

    def setVolume(self, newPercent):
        self.volume = int(max(0, min(100, newPercent)))
        self.player.audio_set_volume(self.volume)
        self.setButtonTitle("volume", f"Volume: {self.volume}%")

    def decrementVolume(self):
        self.setVolume(self.volume - self.volumeModifyAmount)

    def incrementVolume(self):
        self.setVolume(self.volume + self.volumeModifyAmount)

    def isEnded(self):
        return self.player.get_state() == vlc.State.Ended

    def decrementTime(self):
        self.seekTimeSafe(self.currentTime - self.timeModifyAmount)

    def incrementTime(self):
        self.seekTimeSafe(self.currentTime + self.timeModifyAmount)

    def seekPercent(self, percent):
        self.seekTimeSafe((percent * self.currentSongLength) // 100)

    def seekTimeSafe(self, timeMs):
        if(not self.currentSong):
            return

        if(self.currentSongLength == -1):
            return

        self.currentTime = timeMs
        if(self.currentTime >= self.currentSongLength):
            self.setNext()
            return

        timeMs = max(1, min(self.currentSongLength, timeMs))
        playing = self.playing
        
        self.setSong(self.currentSong, addToHistory=False)
        self.currentTime = timeMs

        if(playing):
            self.startPlaying(seekTime=timeMs)
        else:
            self.startPlaying(seekTime=timeMs)
            self.pausePlaying()

    def doQuit(self):
        os._exit(0)

    def loadConfig(self):
        with open("./config.txt", "r") as cfgFile:
            for line in cfgFile:
                line = line.strip()

                if len(line) == 0:
                    continue

                parts = line.split(":")
                parts = [part.strip() for part in parts]

                cmd = parts[0]
                if cmd == "audio directory":
                    self.audioDirectory = parts[1]
                elif cmd == "result file path":
                    self.searchResultPath = parts[1]
                elif cmd == "searchbar script file path":
                    self.searchScriptPath = parts[1]
                elif cmd == "max history stack size":
                    self.maxHistoryStackSize = int(parts[1])
                elif cmd == "accepted audio types":
                    self.acceptedAudioTypes = set(
                        ext.strip().lower() for ext in parts[1].split(","))
                elif cmd == "time modify amount (ms)":
                    self.timeModifyAmount = int(parts[1])
                elif cmd == "volume modify amount (percent)":
                    self.volumeModifyAmount = int(parts[1])
                elif cmd == "folder search limit":
                    self.folderSearchLimit = int(parts[1])
                elif cmd == "macro call limit":
                    self.macroCallLimit = int(parts[1])

    def readMacroFile(self, path):
        path = os.path.join(self.audioDirectory, path)
        with open(path, "r") as file:
            return " ".join(line.strip() for line in file)
                

    def loadSongList(self):
        tempFolderMap = dict()
        self.songs.clear()
        self.folders.clear()
        self.macros.clear()

        self.activeSongs.clear()
        self.songQueue.clear()
        self.historyStack.clear()

        self.currentSong = None
        self.currentTime = 1
        self.activeSongsUpdated()
        self.songQueueUpdated()
        self.currentSongUpdated()

        self.omnifolder = Folder(
            name = "everything",
            searchableName = ".",
            subFolders = self.folders,
            songs = self.songs,
            macros = self.macros
        )

        for root, dirs, files in os.walk(self.audioDirectory):
            # filter out folders staring with .
            dirs[:] = filter(lambda name: name[0] != ".", dirs)

            rootLocalPath = os.path.relpath(root, self.audioDirectory)
            folderSongs = list()
            folderMacros = list()
            subFolders = list()

            isRoot = rootLocalPath == "."
            folderName = "." if isRoot else os.path.basename(root)

            folder = Folder(
                name=folderName,
                searchableName=makeSearchable(folderName),
                subFolders=subFolders,
                songs=folderSongs,
                macros=folderMacros
            )
            self.folders.append(folder)
            tempFolderMap[folderName] = folder
            subFolders.extend(dirs)

            # register songs
            for file in files:
                localPath = os.path.join(rootLocalPath, file)

                fileName = os.path.split(localPath)[1]
                fileNameParts = fileName.split(".")
                fileType = fileNameParts[-1]
                songName = "".join(fileNameParts[:-1]).split("@")[0]
                if(fileType == "smco"):
                    macro = Macro(
                        name=songName,
                        searchableName=makeSearchable(songName),
                        localPath=localPath
                    )
                    self.macros.append(macro)
                    folderMacros.append(macro)
                elif(fileType in self.acceptedAudioTypes):
                    song = Song(
                        name=songName,
                        searchableName=makeSearchable(songName),
                        localPath=localPath)
                    self.songs.append(song)
                    folderSongs.append(song)

        for folder in self.folders:
            subFolderRefs = list()
            for name in folder.subFolders:
                subFolderRefs.append(tempFolderMap[name])
            folder.subFolders[:] = subFolderRefs
        
        self.songs.sort(key=lambda song : len(song.searchableName))
        self.folders.sort(key=lambda fold : len(fold.searchableName))
        self.macros.sort(key=lambda mac : len(mac.searchableName))
        self.activeSongsUpdated()


    def onSongEnd(self):
        songEndThread = threading.Thread(target=self._onSongEnd, daemon=True)
        songEndThread.start()

    def _onSongEnd(self):
        if(self.autoplayActive):
            if(self.loopingActive):
                self.setSong(self.currentSong, addToHistory=False)
                self.startPlaying()
            else:
                self.playNext()

    def setupKeybinds(self):
        threading.Thread(target=self._setupKeybinds, daemon=True).start()

    def _setupKeybinds(self):
        self.ctrlDown = False
        self.shiftDown = False

        if(self.prevKeyHook):
            keyboard.unhook(self.prevKeyHook)
        # threading.Thread(target=lambda:keyboard.hook(self.keyEvent, suppress=True), daemon=True).start()
        self.prevKeyHook = keyboard.hook(self.keyEvent, suppress=True)

        self.keybinds["f"] = self.doSearch

        self.keybinds["space"] = self.togglePlaying
        self.keybinds[","] = self.playPrev
        self.keybinds["."] = self.playNext

        self.keybinds["-"] = self.decrementVolume
        self.keybinds["="] = self.incrementVolume

        self.keybinds["["] = self.decrementTime
        self.keybinds["]"] = self.incrementTime

        self.keybinds["0"] = lambda: self.seekPercent(0)
        self.keybinds["1"] = lambda: self.seekPercent(10)
        self.keybinds["2"] = lambda: self.seekPercent(20)
        self.keybinds["3"] = lambda: self.seekPercent(30)
        self.keybinds["4"] = lambda: self.seekPercent(40)
        self.keybinds["5"] = lambda: self.seekPercent(50)
        self.keybinds["6"] = lambda: self.seekPercent(60)
        self.keybinds["7"] = lambda: self.seekPercent(70)
        self.keybinds["8"] = lambda: self.seekPercent(80)
        self.keybinds["9"] = lambda: self.seekPercent(90)

        self.keybinds["a"] = self.toggleAutoplay
        self.keybinds["l"] = self.toggleLooping
        self.keybinds["c"] = self.clearQueue

        self.keybinds["q"] = self.doQuit
        self.keybinds["r"] = self.reboot
        self.keybinds["t"] = lambda : threading.Thread(
                target=lambda : osascript.run(f"return display alert \"Threads: {threading.active_count()}\""), daemon=True).start()

    def keyEvent(self, e):
        if(self.songStartThread):
            self.songStartThread.join()
        if(e.event_type == "down"):
            if self.ctrlDown and self.shiftDown:
                func = self.keybinds.get(e.name, None)
                if(func):
                    func()
            else:
                if e.name == "shift":
                    self.shiftDown = True
                elif e.name == "ctrl":
                    self.ctrlDown = True
        else:
            if e.name == "shift":
                self.shiftDown = False
            elif e.name == "ctrl":
                self.ctrlDown = False


rad = Radium()
rad.run()
