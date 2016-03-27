# si4703 Raspberry Pi GPIO Python Library

This is a project which contains a simple library for controlling the si4703 device via I2C using a Raspberry Pi and Python

## Installation

Import the library as a module and call the functions.

Example wiring to the Raspberry PI:

  GPIO Pin      |  si4703 Breakout
--------------- | ----------------
2 SDA (BCM)     | I2C SDA         
3 SCL (BCM)     | I2C SCL
5  (BCM)        | RST
19 (BCM)        | GPIO2              
1 (Board 3.3v)  | 3.3V              
6 (Board Gnd)   | GND             

## Usage

There are a few basic funtions for controlling the si4703.

si4703Radio:
Import this into your program using:

```
from si4703Library import si4703Radio
radio = si4703Radio(0x10, 5, 19)
radio.si4703Init()
radio.si4703SetChannel(channel)
radio.si4703SetVolume(volume)
radio.si4703SeekUp()
radio.si4703SeekDown()
radio.si4703GetVolume()
radio.si4703GetChannel()
```

## History

Version 1.0 - 27-Mar-2016 - First release

## Credits

The orginal author of the Arduino library for the si4703: .  Provide much of the foundation for which my Arduino library was based on and thus ported to this library.


## License

GPL
