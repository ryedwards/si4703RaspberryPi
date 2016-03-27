#!/usr/bin/env python 2

#example program for testing the si4703 library
from si4703Library import si4703Radio

def main():
    # device ID is typically 0x10 - confirm with "sudo i2cdetect 1"
    radio = si4703Radio(0x10, 5, 19)
    radio.si4703Init()
    radio.si4703SetChannel(987)
    radio.si4703SetVolume(5)
    print str(radio.si4703GetChannel())
    print str(radio.si4703GetVolume())

    try:
        while True:
            #check for stuff
            kbInput = raw_input(">>")

            if kbInput == "1":
                radio.si4703SeekDown()
                print str(radio.si4703GetChannel())
            if kbInput == "2":
                radio.si4703SeekUp()
                print str(radio.si4703GetChannel())
            if kbInput == "3":
                radio.si4703SetChannel(987)
                print str(radio.si4703GetChannel())
            if kbInput == "+":
                radio.si4703SetVolume(radio.si4703GetVolume()+1)
                print str(radio.si4703GetVolume())
            if kbInput == "-":
                radio.si4703SetVolume(radio.si4703GetVolume()-1)
                print str(radio.si4703GetVolume())
            if kbInput == "r":
                pass
            
    except KeyboardInterrupt:
        print "Exiting program"
        
    print "Shutting down radio"
    radio.si4703ShutDown()
    
if __name__ == "__main__":
    main()