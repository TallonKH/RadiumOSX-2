import mutagen
import time
import pygame

mixer = pygame.mixer
mixer.init()
# mixer.music.load("/Users/tt4/Music/Root/Games/Deltarune/Ferris Wheel.flac")
# mixer.music.load("/Users/tt4/Music/Root/Games/Deltarune/Empty Town@4NI-l_8bmV0.mp3")
pygame.mixer.pre_init(buffer=512, frequency=44100)
mixer.music.load("/Users/tt4/Music/Root/Misc/Wolfie's Just Fine@qG8iAtpavK4.m4a")
mixer.music.play()
print(round(mutagen.File("/Users/tt4/Music/Root/Games/Deltarune/A Real Boy!.flac").info.length * 1000))
while True:
      
    print("Press 'p' to pause, 'r' to resume")
    print("Press 'e' to exit the program")
    query = input(str(mixer.music.get_pos()) + "  ")
    # query = input(" ")
    if query == 'p':
  
        # Pausing the music
        mixer.music.pause()     
    elif query == 'r':
  
        # Resuming the music
        mixer.music.play()
    elif query == "4":
        mixer.music.set_pos(0)
    elif query == "l":
        mixer.music.stop()
        mixer.music.load("/Users/tt4/Music/Root/Games/Deltarune/Empty Town@4NI-l_8bmV0.mp3")
        mixer.music.play()
    elif query == "k":
        mixer.music.stop()
        mixer.music.load("/Users/tt4/Music/Root/Games/Deltarune/Ferris Wheel.flac")
        mixer.music.play()
        mixer.music.set_volume(0)
        time.sleep(0.05)
        mixer.music.set_volume(1)

    elif query == 'e':
  
        # Stop the mixer
        mixer.music.stop()
        break