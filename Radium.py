from collections import namedtuple
from typing import List, Tuple
import vlc
import random
import threading
import os
import osascript
import keyboard
import time

from StringSearch import stringSearch, makeSearchable, searchableChars
from RadiumStatusIcon import RadiumStatusIcon


Folder = namedtuple("Folder", ["name", "searchableName", "subFolders", "songs", "macros"])
Macro = namedtuple("Macro", ["name", "searchableName", "contents"])
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

        self.searchProcess = None

        self.ctrlDown = False
        self.shiftDown = False

        self.keybinds = dict()
        self.acceptedAudioTypes = None
        self.maxHistoryStackSize: int = 30
        self.folderSearchLimit = 5

        self.folders: List[Folder] = list()
        self.macros: List[Macro] = list()
        self.songs: List[Song] = list()

        self.activeSongs: Set[Song] = set()
        self.songQueue: List[Song] = list()
        self.historyStack: List[Tuple(Song, int)] = list()

        self.vlcInst = vlc.Instance()
        self.player = self.vlcInst.media_player_new()
        self.statusIcon = RadiumStatusIcon(self)

        self.loopingActive = False
        self.autoplayActive = True
        self.volume = 100
        self.paused = False
        self.currentSong = None

    def playSong(self, song, addToHistory=True, seekTime=0, startPaused = False):
        thred = threading.Thread(target=lambda : self._playSong(song, addToHistory, seekTime, startPaused), daemon=True)
        thred.start()
        

    def _playSong(self, song, addToHistory=True, seekTime=0, startPaused = False):
        # add existing song to history stack
        if(self.currentSong):
            if(addToHistory and (len(self.historyStack) == 0 or self.historyStack[-1][0] != song)):
                prevTime = self.getTime()
                if(prevTime < 5000 or prevTime > self.getDuration() - 5000):
                    prevTime = 0

                self.historyStack.append((self.currentSong, prevTime))

            if(len(self.historyStack) >= self.maxHistoryStackSize):
                self.prevPlayed.pop(0)

        self.currentSong = song
        self.setButtonTitle("song", f"Playing: \"{song.name}\"")

        path = os.path.join(self.audioDirectory, song.localPath)
        self.player.set_media(self.vlcInst.media_new_path(path))


        vol = self.getVolume()
        self.player.audio_set_volume(0)
        if(not startPaused):
            self.paused = False
            self.setButtonTitle("pause", "Paused" if self.paused else "Playing")
            time.sleep(0.05)
            self.player.play()
            time.sleep(0.05)
        self.player.set_time(seekTime)
        self.player.audio_set_volume(vol)
        self.setButtonTitle(
            "songLength", f"Length: {msToStr(self.getDuration())}")

    def doSearch(self):
        # self._handleSearch()
        if(self.searchProcess == None):
            self.searchProcess = threading.Thread(
                target=self._handleSearch, daemon=True)
            self.searchProcess.start()

    def _handleSearch(self):
        result = self.openSearchScript()
        self.searchProcess = None
        if(result):
            self.processSearchEntry(result)

    def processSearchEntry(self, entry):
        entry = entry.lower()
        cmds = filter(len, (cmd.strip() for cmd in entry.split(";")))
        for cmd in cmds:
            self.processSearchCommand(cmd)

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
            # single song mode
            folderSongSNs = [song.searchableName for song in songPool]
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

    def setPaused(self, newState):
        if(self.paused == newState):
            return
        self.paused = newState
        self.setButtonTitle("pause", "Paused" if self.paused else "Playing")
        if(self.paused):
            self.player.pause()
        else:
            if(self.isEnded()):
                self.playSong(self.currentSong, addToHistory=False)
            else:
                self.player.play()

    def togglePaused(self):
        self.setPaused(not self.paused)

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
            "clearQueue", f"Clear queue ({len(self.songQueue)})")

    def activeSongsUpdated(self):
        self.setButtonTitle(
            "activeSongs", f"Active Songs: {len(self.activeSongs)}")

    def clearQueue(self):
        self.songQueue.clear()
        self.songQueueUpdated()

    def songQueuePop(self, index):
        item = self.songQueue.pop(index)
        self.songQueueUpdated()
        return item

    def rebuildAll(self):
        reloadConfig()
        loadSongList()

    def playNext(self):
        if(len(self.songQueue)):
            self.playSong(self.songQueuePop(0))
        else:
            candidateSongs = self.songs
            if(self.activeSongs):
                candidateSongs = list(self.activeSongs)

            self.playSong(random.choice(candidateSongs))

    def playPrev(self):
        if(self.historyStack):
            stakItem = self.historyStack.pop()
            self.playSong(stakItem[0], addToHistory=False,
                          seekTime=stakItem[1])

    def setButtonTitle(self, button, title):
        self.statusIcon.buttons[button].title = title

    def setButtonState(self, button, state):
        self.statusIcon.buttons[button].state = state

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

    def getDuration(self):
        return self.player.get_length()

    def isEnded(self):
        return self.player.get_state() == vlc.State.Ended

    def decrementTime(self):
        self.seekTime(self.getTime() - self.timeModifyAmount)

    def incrementTime(self):
        self.seekTime(self.getTime() + self.timeModifyAmount)

    def seekPercent(self, percent):
        self.seekTime((percent * self.getDuration()) // 100)

    def getTime(self):
        return self.player.get_time()

    def seekTime(self, timeMs):
        self.playSong(self.currentSong, addToHistory=False, seekTime = timeMs, startPaused=self.paused)

    def doQuit(self):
        os._exit(0)

    def run(self):
        self.reloadConfig()
        self.loadSongList()
        self.setupKeybinds()
        self.player.event_manager().event_attach(vlc.EventType.MediaPlayerEndReached, lambda e : self.onSongEnd())
        self.statusIcon.run()

    def reloadConfig(self):
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

    def readMacroFile(self, path):
        return "1111"

    def loadSongList(self):
        tempFolderMap = dict()
        self.songs.clear()
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
                        contents=self.readMacroFile(file)
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

    def onSongEnd(self):
        self.setPaused(True)
        if(self.autoplayActive):
            if(self.loopingActive):
                self.playSong(self.currentSong, addToHistory=False)
            else:
                self.playNext()

    def setupKeybinds(self):
        keyboard.hook(self.keyEvent, suppress=True)

        self.keybinds["f"] = self.doSearch

        self.keybinds["space"] = self.togglePaused
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
        self.keybinds["t"] = lambda : threading.Thread(
                target=lambda : osascript.run(f"return display alert \"Threads: {threading.active_count()}\""), daemon=True).start()

    def keyEvent(self, e):
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