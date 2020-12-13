#!/usr/bin/env python

import argparse
import datetime
import os
import shutil
import cv2
import time

from picamera.array import PiRGBArray
from picamera import PiCamera

from config import WildlifeConfig
from motion import MotionDetection


def create_video_filename(start_time, path):
    return "{}/{}-wildlife.avi".format(path, start_time.strftime("%Y%m%d-%H%M%S"))


last_activity = None
recording_status = "OFF"
recording_color = (255, 255, 225)
recording_info = ""
recording_filename = ""
start_recording_time = None
stop_recording_time = None
video_out = None

ap = argparse.ArgumentParser()
ap.add_argument("-c", "--config", required=True,
                help="path to the JSON configuration file")
args = vars(ap.parse_args())

config = WildlifeConfig(args["config"])

md = MotionDetection(config)

# prepare video storage folder
if config.clean_store_on_startup:
    shutil.rmtree(config.store_path)
os.mkdir(config.store_path)

# Define the codec and create VideoWriter object XVID, x264
fourcc = cv2.VideoWriter_fourcc(*'x264')

# initialize the camera and grab a reference to the raw camera capture
camera = PiCamera()
camera.resolution = config.resolution
camera.framerate = config.frame_rate
rawCapture = PiRGBArray(camera, size=config.resolution)
print("camera model: " + camera.revision)
print("frame rate: " + str(camera.framerate))

# camera to warmup
time.sleep(0.1)

for capture_frame in camera.capture_continuous(rawCapture, format="bgr", use_video_port=True):
    # grab the raw numpy array
    frame = capture_frame.array

    timestamp = datetime.datetime.now()

    motion_rectangles = md.detect_motion(frame)

    motion_status = "no activity"
    motion_status_color = (255, 255, 255)
    for r in motion_rectangles:
        last_activity = datetime.datetime.now()
        if recording_status == "OFF":
            start_recording_time = timestamp
            recording_filename = create_video_filename(start_recording_time, config.store_path)
            video_out = cv2.VideoWriter(recording_filename, fourcc, config.frame_rate,
                                        (config.resolution[0], config.resolution[1]))
        recording_status = "ON"
        recording_color = (0, 0, 255)
        motion_status = "activity"
        motion_status_color = (0, 255, 0)
        cv2.rectangle(frame, (r[0], r[1]), (r[0] + r[2], r[1] + r[3]), motion_status_color, 1)

    if recording_status == "ON" and last_activity < timestamp and \
            (timestamp - last_activity).seconds >= config.min_recording_time_seconds:
        video_out.release()
        video_out = None
        recording_status = "OFF"
        recording_info = ""
        stop_recording_time = timestamp
        recording_color = (255, 255, 255)

    if config.store_video and recording_status == "ON":
        recording_info = " | " + recording_filename + " " + str((timestamp - start_recording_time).seconds)

    timestamp_str = timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
    cv2.putText(frame, motion_status, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, motion_status_color, 2)
    cv2.putText(frame, recording_status, (frame.shape[1] - 50, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.35, recording_color, 2)
    cv2.putText(frame, timestamp_str + recording_info, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35
                , (0, 0, 255), 1)

    # store frame
    if video_out and config.store_video:
        video_out.write(frame)

    if config.show_video:
        cv2.imshow('captured frame', frame)

    rawCapture.truncate(0)

    if cv2.waitKey(1) == ord('q'):
        break

# When everything done, release the capture
# cap.release()
cv2.destroyAllWindows()