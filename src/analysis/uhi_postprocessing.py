import pandas as pd 
import os
os.environ['USE_PYGEOS'] = '0'
import numpy as np
import geopandas as gpd
import rasterio
from shapely.geometry import box, Polygon, Point
from rasterio.plot import show
from rasterio.warp import calculate_default_transform, reproject, Resampling
import contextily as ctx
from matplotlib import pyplot as plt
from shapely.geometry import mapping
from rasterio.mask import raster_geometry_mask, mask
import cv2
from FDD import FDD
from FDD.SURE import SURE
from pyproj import Transformer, CRS
from types import MethodType
import pickle
import boto3
from uhi import *


if __name__ == '__main__':
        
        
    # get relative dir
    #dir = os.path.dirname(__file__)

    # get directory above
    main_dir = "s3://ipsos-dvd/fdd/" #  "/home/dvdijcke"  # os.path.dirname(os.path.dirname(dir))
    data_in = os.path.join(main_dir, 'data', 'in')

    cname = "LC08_L2SP_044033_20220628_20220706_02_T1"
    st_c_masked, qa_band, st_transform, st_crs = readSatellite(cname)

    # # Bounding box around Austin, Texas, metro area
    # # Bounding box coordinates for Austin, Texas metropolitan area
    # minx = -98.345211
    # miny = 29.705602
    # maxx = -96.848323
    # maxy = 30.740314

    # # Bounding box around Houston, Texas, metro area
    # # # Bounding box coordinates for Austin, Texas metropolitan area
    # minx, maxx = -95.823268, -95.069705 # Longitude
    # miny, maxy = 29.523624, 30.110731 # Latitude
    
    # # bounding box around Chicago, Illinois, metro area
    # minx, maxx = -88.140101, -87.524137 # Longitude
    # miny, maxy = 41.444543, 42.348038 # Latitude
    
    # bounding box around sacramento
    minx, maxx = -121.787773, -121.037523 # Longitude
    miny, maxy = 38.246354, 38.922722 # Latitude

    fig, ax = plotHeatMap(minx, maxx, miny, maxy)

    # subset the raster on sacramento area and also on heat island area
    # bounding box around sacramento
    minx, maxx = -121.787773, -121.237523 # Longitude
    miny, maxy = 38.246354, 38.922722 # Latitude
    subset = subsetRaster(cname, minx, maxx, miny, maxy, st_crs)




    fig, ax = plt.subplots(figsize=(8, 8))
    ret = rasterio.plot.show(subset, cmap='RdYlBu_r', ax=ax)
    
    imgseg = cv2.resize(subset.squeeze(), dsize = (0,0), fx=0.075, fy=0.075)
    plt.imshow(imgseg)



    # lower the resolution of the subset image
    # https://rasterio.readthedocs.io/en/latest/topics/resampling.html
    # https://rasterio.readthedocs.io/en/latest/api/rasterio.enums.html#rasterio.enums.Resampling
    # https://rasterio.readthedocs.io/en/latest/topics/resampling.html#resampling
    # https://rasterio.readthedocs.io/en/latest/topics/resampling.html#resampling
    # https://rasterio.readthedocs.io/en/latest/topics/resampling.html#resampling
    
    
    # segment the image

    X = np.indices(imgseg.shape)
    # flatten last two dimensions of X
    X = X.reshape((X.shape[0], -1)).T
    Y = imgseg.flatten()
    
    model = FDD(Y=Y, X = X, level = 16, lmbda = 5, nu = 0.001, iter = 10000, tol = 5e-5, 
        pick_nu = "MS", scaled = True, scripted = False, image=False, rectangle=True)
    num_samples = 225 #  400 # 400 # 400 # 200
    R =  3 # 3 # 3 # 5
    num_gpus = 0.5
    num_cpus = 4
    res = SURE(tuner=True, num_samples=num_samples, model=model, R=R, 
        num_gpus=num_gpus, num_cpus=num_cpus)

    file_name = 'uhi_SURE.pkl'
    with open(file_name, 'wb') as file:
        pickle.dump(res, file)
    
    s3 = boto3.client('s3')
    with open(file_name, "rb") as f:
        s3.upload_fileobj(f, "ipsos-dvd", "fdd/data/uhi_SURE.pkl")

    
    # u, jumps, J_grid, nrj, eps, it = model.run()
    
    # u_scaled = u / np.max(model.Y_raw, axis = -1)
    

    # plt.imsave("test.png", u)