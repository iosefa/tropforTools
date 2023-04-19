import random

import cv2
import matplotlib.pyplot as plt
import numpy as np

from math import atan, pi, sqrt

import pandas as pd
import scipy
from PIL import Image
from skimage import io
from skimage.segmentation import quickshift
from skimage.segmentation import mark_boundaries
from skimage.util import img_as_float
from sklearn.ensemble import RandomForestClassifier

from tropforTools.utils import flatten


def load_image(img):
    try:
        image = io.imread(img)
        return image
    except Exception as e:
        raise Exception(f'Could not import image. Original exception: {e}')


def segment_image(image, ratio=0.85, sigma=0):
    img = img_as_float(image)
    segments = quickshift(img, ratio=ratio, sigma=sigma)
    return segments


def summary_statistics(segment_pixels):
    """
    For each band, compute: min, max, mean, variance, skewness, kurtosis
    """
    features = []
    n_pixels = segment_pixels.shape
    stats = scipy.stats.describe(segment_pixels)
    band_stats = list(stats)
    if n_pixels == 1:
        band_stats[3] = 0.0
    features += band_stats
    return features


def create_objects(image, segments):
    """
    Creates objects based on a given segmentation algorithm
    """
    segment_ids = np.unique(segments)
    objects = []
    for segment_id in segment_ids:
        segment_pixels = image[segments == segment_id]
        segment_stats = summary_statistics(segment_pixels)
        objects.append(
            {
                'id': segment_id,
                'stats': segment_stats
            }
        )
    return objects


def create_hemispherical(img):
    """
    Creates an equal-area hemispherical image from a 360 image.
    :param image_path: path to 360 image.
    :return:
    """
    dim1 = img.shape[0]
    img_h1 = np.zeros((dim1 + 1, dim1 + 1, 3))
    img_h2 = img_h1.copy()
    dim2 = int(dim1 / 2)

    for i in range(-dim2, dim2):
        for j in range(-dim2, dim2):
            if i >= 0:
                ix = dim1
            elif j >= 0:
                ix = dim1 * 2
            else:
                ix = 0
            if i == 0:
                if j < 0:
                    ix = round(dim1 / -2) + ix
                elif j > 0:
                    ix = round(dim1 / 2) + ix
                else:
                    continue
            else:
                ix = round(atan(j / i) * dim1 / pi) + ix
            iy = sqrt(i ** 2 + j ** 2)
            iy2 = round(dim2 * np.arcsin(iy / dim2 / np.sqrt(2)) / pi * 4)
            if 1 <= ix <= dim1 * 2 and 1 <= iy2 <= dim1 // 2:
                img_h2[i + dim2, j + dim2] = img[iy2, ix - 1]

    im_b = np.concatenate((img_h2[:dim2], img_h2[dim2 + 2:]), axis=0)
    im_bb = np.concatenate((im_b[:, :dim2], im_b[:, dim2 + 2:]), axis=1)

    return im_bb


class SkyViewThreshold:
    def __init__(
        self,
        image_path: str,
        threshold=0.5
    ):
        _img = load_image(image_path)
        self.image_path = image_path
        self.img = create_hemispherical(_img)
        self.threshold = threshold * 255
        self.gray_img = cv2.cvtColor(self.img, cv2.COLOR_RGB2GRAY)
        self.binary_img = self.create_binary()
        self.sky_view_factor = self.calculate_svf()

    def create_binary(self):
        binary_img = self.gray_img.copy()
        binary_img[binary_img >= self.threshold] = 255
        binary_img[binary_img < self.threshold] = 0
        return binary_img

    def plot_binary(self):
        im = Image.fromarray(self.binary_img.astype(np.uint8))
        fig = plt.figure("Binary Threshold Image", figsize=(14, 14))
        ax = fig.add_subplot(1, 1, 1)
        ax.imshow(im)
        plt.axis("off")

    def calculate_svf(self):
        total_pixels = self.img.shape[0] * self.img.shape[0]
        hemisphere_pixels = pi * ((self.img.shape[0] / 2) ** 2)
        outside_pixels = total_pixels - hemisphere_pixels

        black_pixels = total_pixels - np.sum(self.binary_img / 255) - outside_pixels
        svf = (hemisphere_pixels - black_pixels) / hemisphere_pixels
        return svf


class SkyViewClassified:
    def __init__(
        self,
        image_path: str,
        training_data_path=None
    ):
        _img = load_image(image_path)
        self.image_path = image_path
        self.img = create_hemispherical(_img)
        self.segments = segment_image(self.img)
        self.objects = create_objects(self.img, self.segments)
        self.objects_df = pd.DataFrame(
            columns=['segment_id', 'nobs', 'b1_min', 'b1_max', 'b2_min', 'b2_max', 'b3_min', 'b3_max', 'b1_mean',
                     'b2_mean', 'b3_mean', 'b1_variance', 'b2_variance', 'b3_variance', 'b1_skewness', 'b2_skewness',
                     'b3_skewness', 'b1_kurtosis', 'b2_kurtosis', 'b3_kurtosis']
        )
        for i, obj in enumerate(self.objects):
            row = flatten(obj['stats'])
            self.objects_df.loc[i] = [i] + row
        self.objects_df_clean = self.objects_df.dropna()
        self.classified_img = None
        if training_data_path:
            self.training_classes = pd.read_csv(training_data_path)
            self.classified_img = self.classify()
        else:
            self.training_classes = pd.DataFrame(
                columns=['class', 'nobs', 'b1_min', 'b1_max', 'b2_min', 'b2_max', 'b3_min', 'b3_max', 'b1_mean', 'b2_mean',
                         'b3_mean', 'b1_variance', 'b2_variance', 'b3_variance', 'b1_skewness', 'b2_skewness',
                         'b3_skewness', 'b1_kurtosis', 'b2_kurtosis', 'b3_kurtosis']
            )
            print('You must create or import training data in order to calculate the sky view factor')

    def plot_rgb(self):
        im = Image.fromarray(self.img.astype(np.uint8))
        fig = plt.figure("Hemispherical Image", figsize=(14, 14))
        ax = fig.add_subplot(1, 1, 1)
        ax.imshow(im)
        plt.axis("off")

    def plot_segments(self):
        img = img_as_float(self.img)
        fig = plt.figure("Segmented Hemispherical Image", figsize=(14, 14))
        ax = fig.add_subplot(1, 1, 1)
        ax.imshow(mark_boundaries(img, self.segments))
        plt.axis("off")

    def plot_classes(self):
        if not self.classified_img:
            print('Image has not yet been classified.')
            return
        fig = plt.figure("Classified Hemispherical Image", figsize=(14, 14))
        ax = fig.add_subplot(1, 1, 1)
        ax.imshow(self.classified_img)
        plt.axis("off")

    def create_training_data(self, n_samples=500):
        sample = random.sample(list(self.objects_df_clean['segment_id'].values), n_samples)
        img = img_as_float(self.img)
        for j, i in enumerate(sample):
            print(f'working on segment {i} ({j}/500)')
            mask = np.ma.masked_where(self.segments != i, self.segments)
            valid_pixels = np.argwhere(~np.isnan(mask))
            y_min, x_min = tuple(np.min(valid_pixels, axis=0))
            y_max, x_max = tuple(np.max(valid_pixels, axis=0))

            x_min = x_min if x_min - 100 < 0 else x_min - 100
            y_min = y_min if y_min - 100 < 0 else y_min - 100
            x_max = x_max if x_max + 100 > self.segments.shape[0] else x_max + 100
            y_max = y_max if y_max + 100 > self.segments.shape[0] else y_max + 100

            fig = plt.figure(f"Segment {i}")
            ax = fig.add_subplot(1, 1, 1)
            ax.imshow(img)
            ax.imshow(mask)
            plt.axis("off")

            ax.imshow(mark_boundaries(img, mask))
            plt.axis([x_min, x_max, y_min, y_max])
            plt.show()

            klass = input("Enter class or type 'end' to end.")
            if klass == 'end':
                break
            self.training_classes.loc[len(self.training_classes)] = [klass] + list(
                self.objects_df.loc[self.objects_df['segment_id'] == i].values[0]
            )[1:]
            # clear_output(wait=True)

    def import_training_data(self, training_data_path):
        self.training_classes = pd.read_csv(training_data_path)

    def classify(self):
        x_train = self.training_classes.drop(['class'], axis=1)
        y_train = self.training_classes['class']
        x_test = self.objects_df.drop(['segment_id'], axis=1).dropna()
        rf = RandomForestClassifier()
        rf.fit(x_train, y_train)
        y_pred = rf.predict(x_test)
        segment_ids = list(self.objects_df_clean['segment_id'].values)
        classified_img = self.img.copy()
        for i, segment_id in enumerate(segment_ids):
            idx = np.argwhere(self.segments == segment_id)
            for j in idx:
                classified_img[j[0], j[1], 0] = y_pred[i]

        return classified_img[:, :, 0]

    def calculate_svf(self):
        if not self.classified_img:
            print('Image has not yet been classified.')
            return
        total_pixels = self.img.shape[0] * self.img.shape[0]
        hemisphere_pixels = pi * ((self.img.shape[0] / 2) ** 2)
        outside_pixels = total_pixels - hemisphere_pixels

        black_pixels = total_pixels - np.sum(self.classified_img / 255) - outside_pixels
        svf = (hemisphere_pixels - black_pixels) / hemisphere_pixels
        return svf
