from typing import Union
import numpy as np
import cv2
import glob
import os
import argparse
import natsort
import tensorflow as tf
import matplotlib.pyplot as plt
import tensorflow_addons as tfa
import math
import random

parser = argparse.ArgumentParser()
parser.add_argument("--rgb_path",     type=str,   help="raw image path", default='./data_augmentation/raw_data/celebahq/rgb/')
parser.add_argument("--mask_path",     type=str,   help="raw mask path", default='./data_augmentation/raw_data/celebahq/mask/')
parser.add_argument("--output_path",     type=str,   help="Path to save the conversion result", default='./data_augmentation/raw_data/celebahq/select/')

args = parser.parse_args()

# 0920 15:40 829까지 작업

class ImageAugmentationLoader():
    def __init__(self, args):
        """
        Args
            args  (argparse) : inputs (rgb, mask)
                >>>    rgb : RGB image.
                >>>    mask : segmentation mask.
        """
        self.RGB_PATH = args.rgb_path
        self.MASK_PATH = args.mask_path
        
        self.OUTPUT_PATH = args.output_path

        self.OUT_RGB_PATH = self.OUTPUT_PATH + 'rgb/'
        self.OUT_MASK_PATH = self.OUTPUT_PATH + 'mask/'
        
        os.makedirs(self.OUT_RGB_PATH, exist_ok=True)
        os.makedirs(self.OUT_MASK_PATH, exist_ok=True)
        

        self.rgb_list = glob.glob(os.path.join(self.RGB_PATH+'*.jpg'))
        self.rgb_list = natsort.natsorted(self.rgb_list,reverse=True)

        # self.mask_list = glob.glob(os.path.join(self.MASK_PATH+'*.png'))
        # self.mask_list = natsort.natsorted(self.mask_list,reverse=True)


    def merge_masks(self, mask_list, rgb_image):
        rgb_shape = rgb_image.shape[:2]
        zero_maks = np.zeros(rgb_shape, np.uint8)

        for mask_path in mask_list:
            
            mask = cv2.imread(mask_path)
            # mask = tf.image.resize(mask, rgb_shape, tf.image.ResizeMethod.NEAREST_NEIGHBOR).numpy()
            mask = cv2.resize(mask, rgb_shape)
            mask = cv2.cvtColor(mask, cv2.COLOR_BGR2GRAY)
            mask = np.where(mask >= 1, 1, 0).astype(np.uint8)
            zero_maks += mask

        zero_maks = np.where(zero_maks>=1, 1, 0).astype(np.uint8)
        zero_maks = np.expand_dims(zero_maks, axis=-1)
        return zero_maks


    def save_images(self, rgb, mask, prefix):
        cv2.imwrite(self.OUT_RGB_PATH + prefix +'_rgb.jpg', rgb)
        cv2.imwrite(self.OUT_MASK_PATH + prefix + '_mask.png', mask)

                                                              
if __name__ == '__main__':
    """
    Image augmentation can be selected according to the option using the internal function of ImageAugmentationLoader.
    """
    from tqdm import tqdm

    image_loader = ImageAugmentationLoader(args=args)
    rgb_list = image_loader.rgb_list


    # for idx in range(len(rgb_list)):
    for idx in tqdm(range(len(rgb_list)), total=len(rgb_list)):
        rgb_name = rgb_list[idx]
        
        # split rgb name ( ./data_augmentation/raw_data/celebahq/rgb/29999.jpg ) 
        sample_name = rgb_name.split('/')[5].split('.')[0]
        
        sample_masks = glob.glob(image_loader.MASK_PATH + sample_name + '*')
        
        
        original_rgb = cv2.imread(rgb_list[idx])

        original_mask = image_loader.merge_masks(mask_list=sample_masks, rgb_image=original_rgb)

        contours, _ = cv2.findContours(
                original_mask, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
        
        zero_maks = np.zeros(original_mask.shape, np.uint8)
        zero_maks = cv2.drawContours(zero_maks, contours, 0, 1, thickness=-1)

        original_mask += zero_maks
        
        original_mask = np.where(original_mask>=1, 255, 0).astype(np.uint8)
        image_loader.save_images(rgb=original_rgb, mask=original_mask, prefix='human_segmentation_dataset_celeba_{0}_'.format(idx))