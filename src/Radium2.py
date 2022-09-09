import os
import random
import threading
import time
import re
from collections import namedtuple
from typing import List, Tuple
import mutagen
import pygame
import keyboard
import osascript

from RadiumStatusIcon import RadiumStatusIcon
from StringSearch import makeSearchable, searchableChars, stringSearch

Folder = namedtuple(
    "Folder", ["name", "searchableName", "subFolders", "songs", "macros"])
Macro = namedtuple("Macro", ["name", "searchableName", "localPath"])
Song = namedtuple("Song", ["name", "searchableName", "localPath"])

mixer = pygame.mixer
mixer.init()
music = mixer.music

def msToStr(ms):
    ms //= 1000
    if(ms >= 3600):
        return f"{ms//3600:02d}:{(ms//60)%60:02d}:{ms%60:02d}"
    else:
        return f"{(ms//60)%60:02d}:{ms%60:02d}"


class Radium:
    def __init__(self):
        self.versionStr = "3.0"
        self.audioDirectory: str = None

        self.searchThread = None

        self.held_keys = set()
        self.key_bindings = key_bindings = {
            "f": self.doSearch,
            "space": self.togglePaused,
            ",": self.playPrev,
            ".": self.playNext,
            "z": self.playPrev,
            "x": self.playNext,
            "[": self.decrementTime,
            "]": self.incrementTime,
            "0": lambda: self.seekPercent(0),
            "1": lambda: self.seekPercent(10),
            "2": lambda: self.seekPercent(20),
            "3": lambda: self.seekPercent(30),
            "4": lambda: self.seekPercent(40),
            "5": lambda: self.seekPercent(50),
            "6": lambda: self.seekPercent(60),
            "7": lambda: self.seekPercent(70),
            "8": lambda: self.seekPercent(80),
            "9": lambda: self.seekPercent(90),
            "a": self.toggleAutoplay,
            "l": self.toggleLooping,
            "c": self.clearQueue,
            "q": self.doQuit,
            "r": self.reboot,
        }

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

        self.statusIcon = None

        self.loopingActive = False
        self.autoplayActive = True
        self.volume = 1
        self.paused = False

        self.currentSong = None
        self.currentSongLength = 1

        self.prevKeyHook = None

        self.queuedStatusIconTasks = list()
        self.statusIconQueueLock = threading.Lock()
        self.statusIconQueueThread = None

    # ================================
    #          Fundamentals
    # ================================
    def run(self):
        self.reboot()
        self.startStatusIcon()

    def reboot(self):
        try:
            self.loadConfig()
            self.loadSongList()
            self.setupKeybinds()
        except BaseException as excep:
            print(excep)

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

    def doQuit(self):
        os._exit(0)

    # ================================
    #         Searching
    # ================================

    def doSearch(self):
        self._handleSearch()
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

            macroPool.sort(key=lambda mac: len(mac.searchableName))
            folderMacroSNs = list(mac.searchableName for mac in macroPool)
            foundIndices = stringSearch(pathParts[-1], folderMacroSNs, 1)
            if(len(foundIndices) == 0):
                return None

            macroContents = self.readMacroFile(
                self.macros[foundIndices[0]].localPath)
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
            songPool.sort(key=lambda song: len(song.searchableName))
            # single song mode
            folderSongSNs = list(song.searchableName for song in songPool)
            foundIndices = stringSearch(pathParts[-1], folderSongSNs, 1)
            return [songPool[i] for i in foundIndices]

    def openSearchScript(self):
        ret, result, err = osascript.run(
            "return display dialog \"\" default answer \"\"")
        if(ret):
            return None

        entry = result.split(":")[2]
        if(len(entry.strip()) == 0):
            return None
        return entry

    # ================================
    #              Events
    # ================================

    def onSongChanged(self):
        self.setButtonTitle("song", f"Playing: \"{self.currentSong.name}\"")
        self.setButtonTitle("songLength", f"Length: {msToStr(self.currentSongLength)}")

    def onTimeChanged(self):
        pass

    def setLooping(self, newState):
        self.loopingActive = newState
        self.setButtonState("loop", self.loopingActive)

        # pygame has built-in looping, which can only be triggered in mixer.music.play,
        # hence why playSame is called here
        self._playSame()

    def toggleLooping(self):
        self.setLooping(not self.loopingActive)

    def setAutoplay(self, newState):
        self.autoplayActive = newState
        self.setButtonState("autoplay", self.autoplayActive)

    def toggleAutoplay(self):
        self.setAutoplay(not self.autoplayActive)

    def activeSongsUpdated(self):
        self.setButtonTitle(
            "activeSongs", f"Active Songs: {len(self.activeSongs) or len(self.songs)}")

    # ================================
    #              Queue
    # ================================

    def songQueueUpdated(self):
        self.setButtonTitle(
            "clearQueue", f"Queue Size: {len(self.songQueue)}")

    def clearQueue(self):
        self.songQueue.clear()
        self.songQueueUpdated()

    def songQueuePop(self, index):
        item = self.songQueue.pop(index)
        self.songQueueUpdated()
        return item

    # ================================
    #          Status Icon
    # ================================
    def startStatusIcon(self):
        if(self.statusIcon):
            self.statusIcon.kill()
        self.statusIcon = RadiumStatusIcon(self)
        self.statusIcon.run()

    def queueStatusIconTask(self, task):
        if(self.statusIcon):
            task()

    def _setButtonTitle(self, button, title):
        self.statusIcon.buttons[button].title = title

    def setButtonTitle(self, button, title):
        self.queueStatusIconTask(lambda: self._setButtonTitle(button, title))

    def _setButtonState(self, button, state):
        self.statusIcon.buttons[button].state = state

    def setButtonState(self, button, state):
        self.queueStatusIconTask(lambda: self._setButtonState(button, state))

    # ================================
    #             Pausing
    # ================================
    def pausedUpdated(self):
        self.setButtonTitle("pause", "Paused" if self.paused else "Playing")

    def unpause(self):
        self.paused = False
        music.unpause()
        self.pausedUpdated()

    def pause(self):
        self.paused = True
        music.unpause()
        self.pausedUpdated()

    def togglePaused(self):
        if self.paused:
            self.pause()
        else:
            self.unpause()

    # ================================
    #       Setting Active Song
    # ================================
    def playSong(self, song, addToHistory=True):
        path = os.path.join(self.audioDirectory, song.localPath)

        # if a song is currently playing, consider adding it to the history
        if self.currentSong:
            # add the song to the stack, unless it's already at the tail of the stack
            if addToHistory and (len(self.historyStack) == 0 or self.historyStack[-1][0] != song):

                # get the song's current time; store it as 0 it's too close to the start/end
                prevTime = music.get_pos()
                if prevTime < 5000 or prevTime > self.currentSongLength - 5000:
                    prevTime = 0

                self.historyStack.append((self.currentSong, prevTime))

            # if history stack too large, discard the first item
            if len(self.historyStack) >= self.maxHistoryStackSize:
                self.historyStack.pop(0)
        
        # use mutagen to calculate the song duration
        # mut = mutagen.File(song)
        # if mut:
        #     self.currentSongLength = round(mut.info.length * 1000)
        self.currentSong = song
        self.onSongChanged()

        # load the new audio
        print(path)
        music.load(path)

        self._playNew()

    # play the loaded audio
    def _playNew(self):
        # loop indefinitely (-1) if looping is enabled
        music.play(-1 if self.loopingActive else 0)

        # temporarily mute to hide first note stuttering
        music.set_volume(0)
        time.sleep(0.05)
        music.set_volume(self.volume / 100)

    # call music.play again, without changing the current song/time
    def _playSame(self):
        currentTime = music.get_pos()
        self._playNew()
        self.seekTime(currentTime)

    # play the next song in the queue (or, if the queue is empty, a random active song)
    def playNext(self):
        if len(self.songQueue):
            self.playSong(self.songQueuePop(0))
        else:
            candidateSongs = self.songs
            if self.activeSongs:
                candidateSongs = list(self.activeSongs)

            self.playSong(random.choice(candidateSongs))

    # play the previous song in the history stack
    def playPrev(self):
        if len(self.historyStack):
            stackItem = self.historyStack.pop()
            self.playSong(stackItem[0], addToHistory=False)
            self.seekTime(stackItem[1])

    # ================================
    #             Seeking
    # ================================

    def getTime(self):
        return music.get_pos()

    def seekTime(self, ms):
        ms = max(0, ms)
        if ms >= self.currentSongLength:
            self.playNext()
            return

        print("time sought", ms)
        music.set_pos(ms)

    def decrementTime(self):
        self.seekTime(self.getTime() - self.timeModifyAmount)

    def incrementTime(self):
        self.seekTime(self.getTime() + self.timeModifyAmount)

    def seekPercent(self, percent):
        self.seekTime((percent * self.currentSongLength) // 100)

    # ================================
    #             Volume
    # ================================

    def setVolume(self, newPercent):
        self.volume = int(max(0, min(100, newPercent)))
        self.setButtonTitle("volume", f"Volume: {self.volume}%")
        music.set_volume(self.volume / 100)

    def decrementVolume(self):
        self.setVolume(self.volume - self.volumeModifyAmount)

    def incrementVolume(self):
        self.setVolume(self.volume + self.volumeModifyAmount)

    # ================================
    #             Setup
    # ================================

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
        self.currentSongLength = 0
        self.activeSongsUpdated()
        self.songQueueUpdated()

        self.omnifolder = Folder(
            name="everything",
            searchableName=".",
            subFolders=self.folders,
            songs=self.songs,
            macros=self.macros
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

        self.songs.sort(key=lambda song: len(song.searchableName))
        self.folders.sort(key=lambda fold: len(fold.searchableName))
        self.macros.sort(key=lambda mac: len(mac.searchableName))
        self.activeSongsUpdated()


    # ================================
    #       Handling Key Presses
    # ================================
    def isRelevantKeyPress(self):
        return ("ctrl" in self.held_keys)\
            and ("shift" in self.held_keys)\
            and ("command" not in self.held_keys)\
            and ("alt" not in self.held_keys)

    def setupKeybinds(self):
        keyboard.unhook_all()
        keyboard.hook(self.keyEvent, suppress=True)

    def keyEvent(self, e):
        if e.event_type == "down":
            self.held_keys.add(e.name)

            if self.isRelevantKeyPress():
                func = self.key_bindings.get(e.name)
                if func:
                    func()
        else:
            self.held_keys.remove(e.name)


rad = Radium()
rad.run()
