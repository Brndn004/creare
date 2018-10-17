#!/usr/bin/env python

import genpy.rostime
import imutils
import numpy as np
import rosbag
import subprocess
import sys
import time
import yaml

from helper_functions import CentroidFinder, NoiseFilter, PnPSolver
from helper_functions import convert_image, rectify, show_image

class Timer(object):
  def __init__(self, name=None):
    self._name = name
  def __enter__(self):
    self._tstart = time.time()
  def __exit__(self, type, value, traceback):
    if self._name:
        print '[%s]' % self._name,
    print '\nElapsed: %s seconds' %(time.time() - self._tstart)

def status(length, percent):
  sys.stdout.write('\x1B[2K') # Erase entire current line
  sys.stdout.write('\x1B[0E') # Move to the beginning of the current line
  progress = "Progress: ["
  for i in range(0, length):
    if i < length * percent:
      progress += '='
    else:
      progress += ' '
  progress += "] " + str(round(percent * 100.0, 2)) + "%"
  sys.stdout.write(progress)
  sys.stdout.flush()

if __name__ == "__main__":

  # Set global variables
  flag_show_images = False
  flag_show_debug_images = False
  flag_show_debug_messages = False
  bagpath = sys.argv[1]
  bagdir = bagpath[:bagpath.rfind('/') + 1]
  bagname = bagpath[bagpath.rfind('/') + 1:]
  filename = bagdir + 'CSV_' + bagname[:-4] + '.csv'
  rosbag_t0 = None
  poses = []
  poses.append('time[s.ns],x[m],y[m],z[m],yaw[deg],pitch[deg],roll[deg],rx[deg],ry[deg],rz[deg]\n')
  des_start = 0
  if len(sys.argv) > 2:
    des_start = int(sys.argv[2])

  # Get camera info and rosbag start time
  with rosbag.Bag(bagpath) as bag:
    for topic, msg, t in bag.read_messages():
      if rosbag_t0 is None: 
        rosbag_t0 = t.to_sec()
        des_start = rosbag_t0 + des_start
      if topic == '/camera/camera_info':
        mtx = np.array([msg.K[0:3],msg.K[3:6],msg.K[6:9]])
        dist = np.array(msg.D)
        break

  mtx = np.array([[990.6089386924126, 0, 649.8683709187349], [0, 992.4546641961812, 493.67582459076], [0, 0, 1]])
  dist = np.array([-0.331452753057412, 0.105959239301334, -0.0003981374517582984, -0.0002246535214772431, 0])

  # Create processing objects
  cfinder = CentroidFinder(flag_show_debug_images,flag_show_debug_messages)
  nfilter = NoiseFilter(flag_show_debug_images,flag_show_debug_messages)
  # We rectify the image before finding centroids, so the points passed to the PnPSolver do not have any distortion. Set the distortion matrix for the PnPSolver to zero. 
  pnp_dist = 0
  psolver = PnPSolver(mtx, pnp_dist, flag_show_debug_images,flag_show_debug_messages)

  # Set variables to determine progress
  info_dict = yaml.load(subprocess.Popen(['rosbag', 'info', '--yaml', bagpath], stdout=subprocess.PIPE).communicate()[0])
  duration = info_dict['duration']
  start_time = info_dict['start']
  
  with Timer():
    with open(filename,'w') as f:
      with rosbag.Bag(bagpath) as bag:
        last_time = time.clock()
        for topic, msg, t in bag.read_messages(start_time=genpy.rostime.Time(des_start)):

          if time.clock() - last_time > .1:
            percent = (t.to_sec() - start_time) / duration
            status(40, percent)
            last_time = time.clock()        

          if topic == '/camera/image_raw':

            # Convert ROS message to OpenCV image
            img = convert_image(msg, flag = flag_show_debug_images)
            show_image('original', img, flag = flag_show_images)

            # Rotate image if using Yellow Hex
            if False:
              img = imutils.rotate_bound(img, 90)
              show_image('rotated', img, flag = flag_show_images)

            # Rectify image
            img = rectify(img, mtx, dist)
            show_image('rectified', img, flag = flag_show_images)

            # Find initial centroids
            centroids, img_cent = cfinder.get_centroids(img)
            show_image('initial centroids', img_cent, flag = flag_show_images)

            # Process for noise
            filtered, img_filt = nfilter.filter_noise(img, centroids)
            show_image('filtered centroids', img_filt, flag = flag_show_images)

            # Solve for pose
            position, yawpitchroll, orientation, img_solv = psolver.solve_pnp(img, filtered)
            show_image('found feature', img_solv, duration = 1, flag = flag_show_images)

            # Save pose with bag time to list
            x,y,z = position
            yaw,pitch,roll = yawpitchroll
            rx,ry,rz = orientation
            if x is None:
              poses.append('%d.%0.9d,%s,%s,%s,%s,%s,%s,%s,%s,%s\n' %(t.secs,t.nsecs,x,y,z,yaw,pitch,roll,rx,ry,rz))
            else:
              poses.append('%d.%0.9d,%0.5f,%0.5f,%0.5f,%0.5f,%0.5f,%0.5f,%0.5f,%0.5f,%0.5f\n' %(t.secs,t.nsecs,x,y,z,yaw,pitch,roll,rx,ry,rz))

            # In the event of an error, we don't want to lose too much information. Save to file every so many lines.
            if len(poses) > 10:
              # Write to file
              for p in poses:
                f.write(p)
              poses = []

        # Write the final few poses to file
        for p in poses:
          f.write(p)        
        status(40, 1)
