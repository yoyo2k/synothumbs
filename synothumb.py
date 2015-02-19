#!/usr/bin/env python
# sudo mount_nfs -P 192.168.0.2:/volume1/photo /Users/phillips321/nfsmount
# Author:       phillips321
# License:      CC BY-SA 3.0
# Use:          home use only, commercial use by permission only
# Released:     www.phillips321.co.uk
# Dependencies: PIL, libjpeg, libpng, dcraw, ffmpeg/avconv
# Supports:     jpg, bmp, png, tif
# Version:      5.1
# ChangeLog:
#       v5.1 - rewritten, more pythonic
#       v5.0 - addition of PREVIEW thumbnail type; check for proper video
#              conversion command
#       v4.0 - addition of autorate (thanks Markus Luisser)
#       v3.1 - filename fix (_ instead of :) and improvement of rendering 
#              (antialias and quality=90 - thanks to alkopedia)
#       v3.0 - Video support 
#       v2.1 - CR2 raw support
#       v2.0 - multithreaded
#       v1.0 - First release
# ToDo:
#       add more raw formats
#       add more movie formats
import os
import sys
import Queue
import threading
import time
import subprocess
import shlex
import multiprocessing

try:
    from PIL import Image, ImageChops
except ImportError:
    raise Exception("Install PIL")

try:
    from cStringIO import StringIO
except:
    from StringIO import StringIO


#########################################################################
# Settings
#########################################################################
NumOfThreads = multiprocessing.cpu_count() + 1  # Number of threads
# possibly add other raw types?
imageExtensions = ['.jpg','.png','.jpeg','.tif','.bmp','.cr2'] 
videoExtensions = ['.mov','.m4v','mp4']
mediaExtensions = imageExtensions + videoExtensions
blackList = [".DS_Store", ".apdisk", "Thumbs.db"]
SYNO_THUMB_NAME = "SYNOPHOTO_THUMB_%s.jpg"
synoThumbSizes = {
    'xl': {
        'name': SYNO_THUMB_NAME % 'XL',
        'size': (1280,1280),
    }, 'l': {
        'name': SYNO_THUMB_NAME % 'L',
        'size': (800,800),
    }, 'b': {
        'name': SYNO_THUMB_NAME % 'B',
        'size': (640,640),
    }, 'm': {
        'name': SYNO_THUMB_NAME % 'M',
        'size': (320,320),
    }, 's': {
        'name': SYNO_THUMB_NAME % 'S',
        'size': (160,160),
    }, 'p': { # Preview, keep ratio, pad with black
        'name': SYNO_THUMB_NAME % 'PREVIEW',
        'size': (120,160),
    },
}

#########################################################################
# Media Class
#########################################################################
class convertMedia(threading.Thread):
    def __init__(self, queue):
        super(convertMedia, self).__init__()
        self.queue = queue
        if self.is_tool("ffmpeg"):
            self.ffmpegcmd = "ffmpeg -loglevel panic -i '%s' -y -ar 44100 -r "
            self.ffmpegcmd += "12 -ac 2 -f flv -qscale 5 -s 320x180 -aspect "
            self.ffmpegcmd += "320:180 '%s/SYNOPHOTO:FILM.flv'"
            self.ffmpegcmdThumb = "ffmpeg -loglevel panic -i '%s' -y -an -ss "
            self.ffmpegcmdThumb += "00:00:03 -an -r 1 -vframes 1 '%s'"
        elif self.is_tool("avconv"):
            self.ffmpegcmd = "avconv -loglevel panic -i '%s' -y -ar 44100 -r "
            self.ffmpegcmd += "12 -ac 2 -f flv -qscale 5 -s 320x180 -aspect "
            self.ffmpegcmd += "320:180 '%s/SYNOPHOTO:FILM.flv'"
            self.ffmpegcmdThumb = "avconv -loglevel panic -i '%s' -y -an -ss "
            self.ffmpegcmdThumb += "00:00:03 -an -r 1 -vframes 1 '%s'"
        else:
            raise Exception("No FFMpeg or AVconv found")
        if self.is_tool("dcraw"):
            self.dcrawcmd = "dcraw -c -b 8 -q 0 -w -H 5 '%s'"
        else:
            self.dcrawcmd = None

    def is_tool(self, name):
        try:
            with open(os.devnull) as null:
                subprocess.Popen([name], stdout=null, stderr=null).communicate()
        except OSError as e:
            if e.errno == os.errno.ENOENT:
                return False
        return True

    def run_tool(self, command):
        cmd = shlex.split(command)
        proc = subprocess.Popen(cmd, stdout = subprocess.PIPE)
        return proc.communicate()[0]

    def do_thumb(self, image, thumbDir, sizes):
        for size in sizes:
            image.thumbnail(synoThumbSizes[size]['size'], Image.ANTIALIAS)
            image.save(
                os.path.join(thumbDir, synoThumbSizes[size]['name']),
                quality = 90)

    def do_video(self, path, fName, thumbDir):
		# Convert video to flv
        self.run_tool(self.ffmpegcmd % (path, thumbDir))
        # Create video thumbs
        tempThumb = os.path.join("/tmp", fName + ".jpg")
        self.run_tool(self.ffmpegcmdThumb % (path, tempThumb))

        image=Image.open(tempThumb)
        self.do_thumb(image, thumbDir, ('xl', 'm'))

    def do_image_orientation(self, image):
        ###### Check image orientation and rotate if necessary
        ## code adapted from: http://www.lifl.fr/~riquetd/auto-rotating-pictures-using-pil.html
        rotate_values = {
            3: 180,
            6: 270,
            8: 90
        }
        key = 274 # cf ExifTags

        exif = image._getexif()

        if key in exif:
            if exif[key] in rotate_values:
                return image.rotate(rotate_values[exif[key]], expand = True)
        return image
        
    def do_image(self, path, fName, fExt, thumbDir):
        # Following if statements converts raw images using dcraw first
        if fExt.lower() == ".cr2" and self.dcrawcmd is not None:
            dcrawcmd = self.dcrawcmd % path
            raw = StringIO(self.run_tool(dcrawcmd))
            image=Image.open(raw)
        else:
            image=Image.open(path)

        image = self.do_image_orientation(image)

        self.do_thumb(image, thumbDir, ('xl', 'l', 'b', 'm', 's'))

        image.thumbnail(synoThumbSizes['p']['size'], Image.ANTIALIAS)
        # pad out image
        image_size = image.size
        preview_img = image.crop(
            (0, 0, synoThumbSizes['p']['size'][0],
            synoThumbSizes['p']['size'][1]))
        offset_x = max((synoThumbSizes['p']['size'][0] - image_size[0]) / 2, 0)
        offset_y = max((synoThumbSizes['p']['size'][1] - image_size[1]) / 2, 0)
        preview_img = ImageChops.offset(preview_img, offset_x, offset_y)
        preview_img.save(
            os.path.join(thumbDir, synoThumbSizes['p']['name']), quality=90)

    def run(self):
        while True:
            path = self.queue.get()
            fDir, fName = os.path.split(path)
            fName, fExt = os.path.splitext(fName)
            thumbDir = os.path.join(fDir, "@eaDir", fName + fExt)
            
            if os.path.isfile(os.path.join(thumbDir, synoThumbSizes['xl']['name'])):
                self.queue.task_done()
                continue
            
            print "    [-] Now working on %s" % (path)

            if os.path.isdir(thumbDir) != 1:
                try: os.makedirs(thumbDir)
                except: continue

            if fExt in videoExtensions:
                self.do_video(path, fName, thumbDir)
            elif fExt in imageExtensions:
                self.do_image(path, fName, fExt, thumbDir)
            
            self.queue.task_done()


def secondsToStr(t):
    return "%d:%02d:%02d.%03d" % \
        reduce(lambda ll,b : divmod(ll[0],b) + ll[1:],
            [(t*1000,),1000,60,60])

def main():
    try:
        rootdir=sys.argv[1]
    except:
        print "Usage: %s directory" % sys.argv[0]
        sys.exit(0)

    queue = Queue.Queue()

    startTime = time.time()
    # Finds all media of type in extensions array
    fileList=[]
    print "[+] Looking for media files and populating queue ..."
    for path, subFolders, files in os.walk(rootdir):
        if "@eaDir" in path:
            continue
        for file in files:
            if file in blackList:
                continue
            ext = os.path.splitext(file)[1].lower()
            if ext in mediaExtensions: # check if extensions matches ext
                fileList.append(os.path.join(path, file))

    print "[+] Have found %i media files in search directory" % len(fileList)
    print "    Time to complete %s" % secondsToStr(time.time() - startTime)
    
    if not len(fileList):
        sys.exit(0)

    raw_input("    Press Enter to continue or Ctrl-C to quit")

    #spawn a pool of threads
    for i in range(NumOfThreads): #number of threads
        t = convertMedia(queue)
        t.setDaemon(True)
        t.start()

    # populate queue with Images
    for path in fileList:
        queue.put(path)

    startTime = time.time()
    queue.join()
    print "    Time to complete %s" % secondsToStr(time.time() - startTime)

if __name__ == "__main__":
    main()

