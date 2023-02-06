import glob
import os
import shutil
import time
import random

loop_count = 50

image_dir = '/home/edge_assets/test_images/casting_defects_inference/'
target_list = ['/home/edge_assets/image_sink_volume/Mfg_Vision_CIS_v2_jp5_Modular/', 
    '/home/edge_assets/image_sink_volume/Mfg_Vision_CIS_v2_jp5_Monolithic/'
    ]

for l in range(loop_count):
    image_files = glob.glob(image_dir + "*.jpg")
    image_count = len(image_files)
    x = 0
    for i in range(image_count):
        i = random.randint(0, image_count -1)
        image_name = image_files[i]
        shutil.copy(image_name, target_list[x])
        x += 1
        time.sleep(1)
        if x == 2:
            x = 0