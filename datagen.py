'''Load image/labels/boxes from an annotation file.

The list file is like:

    img.jpg width height xmin ymin xmax ymax label xmin ymin xmax ymax label ...
'''
from __future__ import print_function

import os
import sys
import random

import torch
import torch.utils.data as data
import torchvision.transforms as transforms

from PIL import Image
from encoder import DataEncoder


class ListDataset(data.Dataset):
    def __init__(self, root, list_file, train, transform, input_size, max_size):
        '''
        Args:
          root: (str) ditectory to images.
          list_file: (str) path to index file.
          train: (boolean) train or test.
          transform: ([transforms]) image transforms.
          input_size: (int) image shorter side size.
          max_size: (int) maximum image longer side size.
        '''
        self.root = root
        self.train = train
        self.transform = transform
        self.input_size = input_size
        self.max_size = max_size

        self.fnames = []
        self.boxes = []
        self.labels = []

        self.data_encoder = DataEncoder()

        with open(list_file) as f:
            lines = f.readlines()
            self.num_samples = len(lines)

        for line in lines:
            splited = line.strip().split()
            self.fnames.append(splited[0])
            num_boxes = (len(splited) - 3) // 5
            box = []
            label = []
            for i in range(num_boxes):
                xmin = splited[3+5*i]
                ymin = splited[4+5*i]
                xmax = splited[5+5*i]
                ymax = splited[6+5*i]
                c = splited[7+5*i]
                box.append([float(xmin),float(ymin),float(xmax),float(ymax)])
                label.append(int(c))
            self.boxes.append(torch.Tensor(box))
            self.labels.append(torch.LongTensor(label))

    def __getitem__(self, idx):
        '''Load image.

        Args:
          idx: (int) image index.

        Returns:
          img: (tensor) image tensor.
          loc_targets: (tensor) location targets.
          cls_targets: (tensor) class label targets.
        '''
        # Load image and boxes.
        fname = self.fnames[idx]
        img = Image.open(os.path.join(self.root, fname))
        boxes = self.boxes[idx]
        labels = self.labels[idx]

        # Data augmentation while training.
        if self.train:
            img, boxes = self.random_flip(img, boxes)
            img, boxes = self.scale_jitter(img, boxes)

        img, boxes = self.resize(img, boxes)
        img = self.transform(img)
        return img, boxes, labels

    def resize(self, img, boxes):
        '''Resize the image shorter side to input_size.

        Args:
          img: (PIL.Image) image.
          boxes: (tensor) object boxes, sized [#obj, 4].

        Returns:
          (PIL.Image) resized image.
          (tensor) resized object boxes.

        Reference:
          https://github.com/rbgirshick/py-faster-rcnn/blob/master/lib/utils/blob.py
        '''
        # im_size_min = min(img.size)
        # im_size_max = max(img.size)
        # scale = float(self.input_size) / float(im_size_min)
        # if round(scale*im_size_max) > self.max_size:  # limit the longer side to MAX_SIZE
        #     scale = float(self.max_size) / float(im_size_max)
        # w = int(img.width*scale)
        # h = int(img.height*scale)
        w = h = self.input_size
        ws = 1.0 * w / img.width
        hs = 1.0 * h / img.height
        scale = torch.Tensor([ws,hs,ws,hs])
        return img.resize((w,h)), scale*boxes

    def random_flip(self, img, boxes):
        '''Randomly flip the image and adjust the boxes.

        For box (xmin, ymin, xmax, ymax), the flipped box is:
        (w-xmax, ymin, w-xmin, ymax).

        Args:
          img: (PIL.Image) image.
          boxes: (tensor) object boxes, sized [#obj, 4].

        Returns:
          img: (PIL.Image) randomly flipped image.
          boxes: (tensor) randomly flipped boxes, sized [#obj, 4].
        '''
        if random.random() < 0.5:
            img = img.transpose(Image.FLIP_LEFT_RIGHT)
            w = img.width
            xmin = w - boxes[:,2]
            xmax = w - boxes[:,0]
            boxes[:,0] = xmin
            boxes[:,2] = xmax
        return img, boxes

    def scale_jitter(self, img, boxes):
        '''Scale image size randomly to [3/4,4/3].

        Args:
          img: (PIL.Image) image.
          boxes: (tensor) object boxes, sized [#obj, 4].

        Returns:
          img: (PIL.Image) scaled image.
          boxes: (tensor) scaled object boxes, sized [#obj, 4].
        '''
        imw, imh = img.size
        sw = random.uniform(3/4., 4/3.)
        sh = random.uniform(3/4., 4/3.)
        w = int(imw*sw)
        h = int(imh*sh)
        img = img.resize((w,h))
        boxes[:,::2] *= sw
        boxes[:,1::2] *= sh
        return img, boxes

    def collate_fn(self, batch):
        '''Pad images and encode targets.

        As for images are of different sizes, we need to pad them to the same size.

        Args:
          batch: (list) of images, cls_targets, loc_targets.

        Returns:
          padded images, stacked cls_targets, stacked loc_targets.

        Reference:
          https://github.com/rbgirshick/py-faster-rcnn/blob/master/lib/utils/blob.py
        '''
        imgs = [x[0] for x in batch]
        boxes = [x[1] for x in batch]
        labels = [x[2] for x in batch]

        max_h = max([im.size(1) for im in imgs])
        max_w = max([im.size(2) for im in imgs])
        num_imgs = len(imgs)
        inputs = torch.zeros(num_imgs, 3, max_h, max_w)

        loc_targets = []
        cls_targets = []
        for i in range(num_imgs):
            im = imgs[i]
            imh, imw = im.size(1), im.size(2)
            inputs[i,:,:imh,:imw] = im

            # Encode data.
            loc_target, cls_target = self.data_encoder.encode(boxes[i], labels[i], input_size=(max_w,max_h), train=self.train)
            loc_targets.append(loc_target)
            cls_targets.append(cls_target)
        return inputs, torch.stack(loc_targets), torch.stack(cls_targets)

    def __len__(self):
        return self.num_samples


def test():
    import torchvision

    transform = transforms.Compose([
        transforms.ToTensor(),
        transforms.Normalize((0.485,0.456,0.406), (0.229,0.224,0.225))
    ])
    dataset = ListDataset(root='/mnt/hgfs/D/download/PASCAL_VOC/voc_all_images',
                          list_file='./voc_data/test.txt', train=False, transform=transform, input_size=600, max_size=1000)
    dataloader = torch.utils.data.DataLoader(dataset, batch_size=4, shuffle=True, num_workers=1, collate_fn=dataset.collate_fn)

    for images, loc_targets, cls_targets in dataloader:
        print(images.size())
        print(loc_targets.size())
        print(cls_targets.size())
        grid = torchvision.utils.make_grid(images, 1)
        torchvision.utils.save_image(grid,'a.jpg')
        break

# test()
