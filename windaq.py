
"""
Created on February, 2019

@author: samper
@edited: timwal (3/4/21)

Windaq class object to work directly with .wdq files
Python 3 Version
"""

# !/usr/bin/python
import struct
import datetime

# Import the library, if file is not within the same directory as your script use sys.path.append()
import pandas as pd
import os
import tkinter as tk
import tkinter.filedialog as fd
import tkinter.messagebox as mb



class windaq(object):
    """
    Read windaq files (.wdq extension) without having to convert them to .csv or other human readable text

    Code based on http://www.dataq.com/resources/pdfs/misc/ff.pdf provided by Dataq, code and comments will refer to conventions from this file
    and python library https://www.socsci.ru.nl/wilberth/python/wdq.py that does not appear to support the .wdq files created by WINDAQ/PRO+
    """

    def __init__(self, filename):
        """ Define data types based off convention used in documentation from Dataq """
        UI = "<H"  # unsigned integer, little endian
        I = "<h"  # integer, little endian
        B = "B"  # unsigned byte, kind of redundant but lets keep consistent with the documentation
        UL = "<L"  # unsigned long, little endian
        D = "<d"  # double, little endian
        L = "<l"  # long, little endian
        F = "<f"  # float, little endian

        ''' Open file as binary '''
        with open(filename, 'rb') as self._file:
            self._fcontents = self._file.read()

        ''' Read Header Info '''
        if struct.unpack_from(B, self._fcontents, 1)[0]:  # max channels >= 144
            self.nChannels = (struct.unpack_from(B, self._fcontents, 0)[0])  # number of channels is element 1
        else:
            self.nChannels = (struct.unpack_from(B, self._fcontents, 0)[0]) & 31  # number of channels is element 1 mask bit 5

        self._hChannels = struct.unpack_from(B, self._fcontents, 4)[0]  # offset in bytes from BOF to header channel info tables
        self._hChannelSize = struct.unpack_from(B, self._fcontents, 5)[0]  # number of bytes in each channel info entry
        self._headSize = struct.unpack_from(I, self._fcontents, 6)[0]  # number of bytes in data file header
        self._dataSize = struct.unpack_from(UL, self._fcontents, 8)[0]  # number of ADC data bytes in file excluding header
        self.nSample = (self._dataSize / (2 * self.nChannels))  # number of samples per channel
        self._trailerSize = struct.unpack_from(UL, self._fcontents, 12)[0]  # total number of event marker, time and date stamp, and event marker comment pointer bytes in trailer
        self._annoSize = struct.unpack_from(UI, self._fcontents, 16)[0]  # total number of usr annotation bytes including 1 null per channel
        self.timeStep = struct.unpack_from(D, self._fcontents, 28)[0]  # time between channel samples: 1/(sample rate throughput / total number of acquired channels)
        e14 = struct.unpack_from(L, self._fcontents, 36)[0]  # time file was opened by acquisition: total number of seconds since jan 1 1970
        e15 = struct.unpack_from(L, self._fcontents, 40)[0]  # time file was written by acquisition: total number of seconds since jan 1 1970
        self.fileCreated = datetime.datetime.fromtimestamp(e14).strftime('%Y-%m-%d %H:%M:%S')  # datetime format of time file was opened by acquisition
        self.fileWritten = datetime.datetime.fromtimestamp(e15).strftime('%Y-%m-%d %H:%M:%S')  # datetime format of time file was written by acquisition
        self._packed = ((struct.unpack_from(UI, self._fcontents, 100)[0]) & 16384) >> 14  # bit 14 of element 27 indicates packed file. bitwise & e27 with 16384 to mask all bits but 14 and then shift to 0 bit place
        self._HiRes = ((struct.unpack_from(UI, self._fcontents, 100)[0]) & 1)  # bit 1 of element 27 indicates a HiRes file with 16-bit data

        ''' read channel info '''
        self.scalingSlope = []
        self.scalingIntercept = []
        self.calScaling = []
        self.calIntercept = []
        self.engUnits = []
        self.sampleRateDivisor = []
        self.phyChannel = []

        for channel in range(0, self.nChannels):
            channelOffset = self._hChannels + (self._hChannelSize * channel)  # calculate channel header offset from beginning of file, each channel header size is defined in _hChannelSize
            self.scalingSlope.append(struct.unpack_from(F, self._fcontents, channelOffset)[0])  # scaling slope (m) applied to the waveform to scale it within the display window
            self.scalingIntercept.append(struct.unpack_from(F, self._fcontents, channelOffset + 4)[0])  # scaling intercept (b) applied to the waveform to scale it withing the display window
            self.calScaling.append(struct.unpack_from(D, self._fcontents, channelOffset + 4 + 4)[0])  # calibration scaling factor (m) for waveform vale display
            self.calIntercept.append(struct.unpack_from(D, self._fcontents, channelOffset + 4 + 4 + 8)[0])  # calibration intercept factor (b) for waveform value display
            self.engUnits.append(struct.unpack_from("cccccc", self._fcontents, channelOffset + 4 + 4 + 8 + 8))  # engineering units tag for calibrated waveform, only 4 bits are used last two are null
            if self._packed:  # if file is packed then item 7 is the sample rate divisor
                self.sampleRateDivisor.append(
                    struct.unpack_from(B, self._fcontents, channelOffset + 4 + 4 + 8 + 8 + 6 + 1)[0])
            else:
                self.sampleRateDivisor.append(1)
            self.phyChannel.append(struct.unpack_from(B, self._fcontents, channelOffset + 4 + 4 + 8 + 8 + 6 + 1 + 1)[0])  # describes the physical channel number

        ''' read user annotations '''
        #print('self._headSize: ',self._headSize,'\nself._dataSize: ',self._headSize,'\nself._trailerSize: ',self._trailerSize)
        aOffset = self._headSize + self._dataSize + self._trailerSize
        aTemp = ''
        #print(aOffset," : ",len(range(0,self._annoSize)))
        for i in range(0, self._annoSize):
            aTemp += struct.unpack_from('c', self._fcontents, aOffset + i)[0].decode("utf-8")
        self._annotations = aTemp.split('\x00')
        self._trailerSize = None
        #print(self._annotations)

    def data(self, channelNumber):
        """ return the data for the channel requested
            data format is saved CH1tonChannels one sample at a time.
            each sample is read as a 16bit word and then shifted to a 14bit value
        """

        dataOffset = self._headSize + ((channelNumber - 1) * 2)
        data = []
        for i in range(0, int(self.nSample)):
            channelIndex = dataOffset + (2 * self.nChannels * i)
            if self._HiRes:
                temp = struct.unpack_from("<h", self._fcontents, channelIndex)[0] * 0.25  # multiply by 0.25 for HiRes data
            else:
                temp = struct.unpack_from("<h", self._fcontents, channelIndex)[0] >> 2  # bit shift by two for normal data
            temp2 = self.calScaling[channelNumber - 1] * temp + self.calIntercept[channelNumber - 1]
            data.append(temp2)
        return data

    def time(self):
        """ return time """
        t = []
        for i in range(0, int(self.nSample)):
            t.append(self.timeStep * i)
        return t

    def unit(self, channelNumber):
        """ return unit of requested channel """
        unit = ''
        for b in self.engUnits[channelNumber - 1]:
            unit += b.decode('utf-8')
        ''' Was getting \x00 in the unit string after decoding, lets remove that and whitespace '''
        unit.replace('\x00', '').strip()
        return unit

    def chAnnotation(self, channelNumber):
        """ return user annotation of requested channel """
        return self._annotations[channelNumber - 1]



"""--------------MAIN--------------"""
# Close dumb blank tk window
root = tk.Tk()
root.withdraw()

# Popup message. If cancelled, exits program.
welp = mb.askokcancel('Warning.','This script will convert all files in the selected folder.')
if not welp: #buttons return boolean values
    exit()

# Asks user for input directory of files
path = fd.askdirectory(title="Please select a folder")
if path == "": # hitting cancel returns a null value string, used to exit program
    mb.showinfo('Cancelled','Cancelled. No file selected.\n\nProgram exited.')
    exit()

# #Comment the following line after testing is done!!!!!
# path='C:/Users/timwal/Documents/AA_TestFolder'


# Iterate through all files in the folder selected above
# Moves files into project folder to be parsed. May be problem outside PyCharm IDE.
import shutil
ii=0
for file in os.listdir(path):
    # checks pathing of selected folder and skips folders, removing will result in errors
    if os.path.isdir(path + '/' + os.listdir(path)[ii]):
        break
    else:
        # copies files to be converted into project folder
        shutil.copy(path + '/' + os.listdir(path)[ii], os.path.abspath(file))

    wfile = windaq(file)

    # Read all data into a pandas Dataframe, this is my preferred way of working with data (-SamPerry)
    df = pd.DataFrame({'time': wfile.time(),
                       'Current Probe': wfile.data(1),
                       'Piston Pressure 2': wfile.data(2),
                       'Piston Pressure 1': wfile.data(3),
                       'Keyence Position': wfile.data(4)})

    new_file = os.path.splitext(file)[0] + '_csv.csv'
    # sends data to csv file with new name
    df.to_csv(new_file, index=False)
    shutil.move(os.path.abspath(new_file),path)
    os.remove(file)

    # # Delete data in the following variables to clear buffer. Absolutely necessary.
    # del new_file
    # del wfile

    ii+=1 #used for indexing
