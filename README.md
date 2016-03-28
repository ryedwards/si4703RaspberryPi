# si4703 Raspberry Pi GPIO Python Library

This is a project which contains a simple library for controlling the si4703 device via I2C using a Raspberry Pi and Python

A breakout board for the si4703 can be found at [SparkFun](https://www.sparkfun.com/products/12938)

This is my first project on the Raspberry Pi so any feedback/tips are greatly appreciated.

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

Import this into your program using:
```
from si4703Library import si4703Radio
```

The class is started with <code>si4703Radio(i2cDeviceID, resetPIN, irqPin)</code>
* i2cDeviceID (required) = The ID for the si4703 - typically 0x10 - can confirm with <code>sudo i2cdetect 1</code>
* resetPIN (required) = GPIO pin connected to the reset line of the si4703
* irqPIN (optional) = GPIO pin connected to the GPIO2 line of the si4703 - if omitted library will use polling to determine end of tuning/seeking

The class contains the following functions for controlling the si4730
```
radio.si4703Init() - Inits all the registers and turns on the radio
radio.si4703SetChannel(channel) - channel is FM frequency without decimal (e.g. 963 = 96.3)
radio.si4703SetVolume(volume) - volume level from 0 (quiet) to 15 (loud)
radio.si4703SeekUp()
radio.si4703SeekDown()
radio.si4703GetVolume() - returns the volume (0-15)
radio.si4703GetChannel() - returns the currently tuned channel (same format as channel above)
radio.si4703ProcessRDS() - grabs the RDS data out of the buffer and parses group 0 and group 2.  Needs to run at least every 40ms to be effective.
radio.si4703ClearRDSBuffers() - Clear the RDS buffers.  Required after a seek/tune to flush out the old station info.
```

The library is currently configured for Europe FM - ToDo is add an option to switch.  For now you'll have to edit the library.
There is some tweaking that can be done with the seek registers to modify sensitivity.

For all the info on the si4703 [read the application notes](http://www.silabs.com/Support%20Documents/TechnicalDocs/AN230.pdf) or [the datasheet](https://www.silabs.com/Support%20Documents/TechnicalDocs/Si4702-03-C19-short.pdf)

An example is provided with the library which exercises most of the functions.

## History

Version 1.0 - 27-Mar-2016 - First release

## Credits

The original author of the Arduino library for the SparkFun si4703: Aaron Weiss & Simon Monk.  This provided much of the foundation for which my Arduino library was based on and thus ported to this library.

## License

GPL
