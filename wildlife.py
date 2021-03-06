#!/usr/bin/env python

import argparse
import datetime
import os
import shutil
import cv2
from signal import signal, SIGINT

import imutils
from imutils.video import FPS

from config import WildlifeConfig
from motion import MotionDetection
from notifier import TelegramNotifier
from video_writer import AsyncVideoWriter

exit_by_handler = False


def signal_handler(signal_received, f):
    global exit_by_handler
    print('[INFO] SIGINT or CTRL-C detected. Exiting gracefully')
    exit_by_handler = True


def create_video_filename(start_time, path):
    return "{}/{}-wildlife.avi".format(path, start_time.strftime("%Y%m%d-%H%M%S"))


start_recording_threshold_t1 = None
start_recording_threshold_t2 = None


def start_recording_threshold(activity_count):
    global start_recording_threshold_t1
    global start_recording_threshold_t2
    if activity_count % 5 == 0:
        start_recording_threshold_t2 = start_recording_threshold_t1
        start_recording_threshold_t1 = datetime.datetime.now()
        if start_recording_threshold_t2 is not None and (
                start_recording_threshold_t1 - start_recording_threshold_t2).seconds < 1:
            return True
    return False


last_activity = None

recording_status = "OFF"
recording_color = (255, 255, 225)
recording_info = ""
recording_filename = ""
start_recording_time = None
stop_recording_time = None
video_out = None
activity_count_total = 0
activity_count_during_recording = 0
last_recording_snapshot = None

signal(SIGINT, signal_handler)

ap = argparse.ArgumentParser()
ap.add_argument("-c", "--config", required=True,
                help="path to the JSON configuration file")
args = vars(ap.parse_args())

config = WildlifeConfig(args["config"])

# prepare video storage folder
if config.clean_store_on_startup:
    shutil.rmtree(config.store_path)
os.mkdir(config.store_path)

if config.system == "raspberrypi":
    from capture_picamera import CapturePiCameraAsync as Capture
else:
    from capture_opencv import CaptureOpencv as Capture

notifier = None
if config.telegram_notification:
    notifier = TelegramNotifier(config)


def writer_finished(file_name):
    global notifier
    if notifier is not None and last_recording_snapshot is not None:
        snapshot_filename = file_name.rsplit('.', 1)[0] + '.jpg'
        cv2.imwrite(snapshot_filename, last_recording_snapshot)
        notifier.send_message("New Wildlife Video: {}".format(os.path.basename(file_name)), snapshot_filename)


capture = Capture(config)

writer = AsyncVideoWriter(config, writer_finished)

motion = MotionDetection(config)

motion_detected = False
motion_rectangles = [(0, 0, config.resolution[0], config.resolution[1])]

capture.start()

fps = FPS().start()

frame_count = 0
while True:
    frame, frame_timestamp = capture.read()

    if frame is None:
        continue

    frame_count += 1

    timestamp = datetime.datetime.now()

    if config.motion_detection and frame_count % 3 == 0:
        motion_detected, motion_rectangles = motion.detect_motion(frame)

    motion_status = "activity"
    motion_status_color = (255, 255, 255)
    if motion_detected:
        last_activity = datetime.datetime.now()
        activity_count_total += 1

        if recording_status == "OFF" and start_recording_threshold(activity_count_total):
            recording_status = "ON"
            recording_color = (0, 0, 255)
            start_recording_time = frame_timestamp
            recording_filename = create_video_filename(start_recording_time, config.store_path)
            if config.store_video:
                activity_count_during_recording = 0
                writer.start(recording_filename)

        activity_count_during_recording += 1
        if activity_count_during_recording == config.store_activity_count_threshold + 1:
            last_recording_snapshot = frame.copy()

        motion_status = "activity"
        motion_status_color = (0, 255, 0)
        if motion_rectangles is not None:
            for r in motion_rectangles:
                cv2.rectangle(frame, (r[0], r[1]), (r[0] + r[2], r[1] + r[3]), motion_status_color, 1)

    if recording_status == "ON" and last_activity < timestamp and \
            (timestamp - last_activity).seconds >= config.min_recording_time_seconds:
        if config.store_video:
            writer.stop(activity_count_during_recording)
        recording_status = "OFF"
        recording_info = ""
        stop_recording_time = timestamp
        recording_color = (255, 255, 255)

    if config.store_video and recording_status == "ON":
        recording_info = " | " + recording_filename + " " + str((frame_timestamp - start_recording_time).seconds) + \
                         " activity: " + str(activity_count_during_recording)

    timestamp_str = frame_timestamp.strftime("%A %d %B %Y %I:%M:%S%p")
    cv2.putText(frame, motion_status, (10, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, motion_status_color, 2)
    cv2.putText(frame, recording_status, (frame.shape[1] - 50, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.35, recording_color, 2)
    cv2.putText(frame, timestamp_str + recording_info, (10, frame.shape[0] - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.35
                , (255, 255, 255), 1)

    # store frame
    if config.store_video:
        writer.write(frame)

    if config.show_video:
        cv2.imshow('captured frame', frame)
        if cv2.waitKey(1) == ord('q'):
            break

    if exit_by_handler:
        break

    fps.update()

# shutdown
fps.stop()
print("[INFO] elapsed time: {:.2f} s".format(fps.elapsed()))
print("[INFO] approx. FPS: {:.2f}".format(fps.fps()))
writer.stop(0)
capture.stop()
if config.show_video:
    cv2.destroyAllWindows()
