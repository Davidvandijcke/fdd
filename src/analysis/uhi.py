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

def readSatellite(cname):
        #------- read satellite data
    # https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/media/files/LSDS-1619_Landsat8-9-Collection2-Level2-Science-Product-Guide-v5.pdf

    # Open the ST_B10 and QA bands
    folder = os.path.join(data_in, 'satellite', cname)
    fn = os.path.join(folder, cname + "_ST_B10.TIF")
    with rasterio.open(fn) as src:
        st_band = src.read(1)  # Note: band indexing in rasterio is 1-based
        st_transform = src.transform
        st_crs = src.crs

    # set fill value -9999 to nan
    st_band = np.where(st_band == 0, np.nan, st_band)

    # filter out values where st_band not between 293 and 61440
    st_band = np.where(st_band < 293, np.nan, st_band)
    st_band = np.where(st_band >= 61440, np.nan, st_band)

    # ST_QA band contains the uncertainty of the ST band, in Kelvin.
    fn = os.path.join(folder, cname + "_ST_QA.TIF")
    with rasterio.open(fn) as src:
        qa_band = src.read(1)

    # Apply scale factor to convert digital numbers to temperature in Kelvin
    st_k = st_band * 0.00341802 + 149

    qa_band = np.where(qa_band == 0, np.nan, st_band)

    qa_band = qa_band * 0.01 # https://d9-wret.s3.us-west-2.amazonaws.com/assets/palladium/production/s3fs-public/atoms/files/LSDS-1328_Landsat8-9-OLI-TIRS-C2-L2-DFCB-v6.pdf p.5

    # Convert Kelvin to Celsius
    st_c = st_k - 273.15

    # Define a threshold for QA values
    qa_threshold = 2  # max 2 degrees Kelvin uncertainty

    # Apply QA mask to ST band
    # leaving this for now, it's something annoying with bit-packed numbers
    #st_c_masked = np.where(qa_band < qa_threshold, st_c, np.nan)
    return st_c, qa_band, st_transform, st_crs

def plotHeatMap(minx, maxx, miny, maxy):

    # create a polygon from the bounding box    
    bbox = box(minx, miny, maxx, maxy)

    # create a geodataframe with the polygon
    gdf = gpd.GeoDataFrame({'geometry': bbox}, index=[0], crs="epsg:4326")
    gdf = gdf.to_crs(st_crs)

    extent = [gdf.bounds.minx[0], gdf.bounds.maxx[0], gdf.bounds.miny[0], gdf.bounds.maxy[0]]

    fig, ax = plt.subplots(figsize=(12, 12))
    ret = rasterio.plot.show(st_c_masked, cmap='RdYlBu_r', ax=ax, transform=st_transform)
    img = ret.get_images()[0]
    fig.colorbar(img, ax=ax, fraction=.05)
    
    ax.set_xlim(extent[0], extent[1])
    ax.set_ylim(extent[2], extent[3])

    # plot the geodataframe on top of the raster
    gdf.plot(ax=ax, facecolor="none", edgecolor='black', alpha=0.5)

    # add basemap   
    ctx.add_basemap(ax, crs=st_crs, alpha=0.5, source=ctx.providers.Stamen.TonerLite)
    
    return fig, ax

def subsetRaster(cname, minx, maxx, miny, maxy, st_crs):
    
    folder = os.path.join(data_in, 'satellite', cname)
    fn = os.path.join(folder, cname + "_ST_B10.TIF")
    # Define your bounding box and create a polygon
    # Define points in the old CRS
    lower_left = Point(minx, miny)
    upper_right = Point(maxx, maxy)

    # Define a transformer from the old CRS to the new CRS
    transformer = Transformer.from_crs(CRS.from_epsg(4326), st_crs, always_xy=True)

    # Transform the points to the new CRS
    lower_left_transformed = transformer.transform(*lower_left.coords[0])
    upper_right_transformed = transformer.transform(*upper_right.coords[0])

    # create the bounding box in the new CRS
    bbox = box(*lower_left_transformed, *upper_right_transformed)

    # create a GeoDataFrame with the polygon
    gdf = gpd.GeoDataFrame({'geometry': bbox}, index=[0], crs=st_crs)
    
    # Transform the GeoDataFrame to a format that can be used by rasterio
    geoms = gdf.geometry.values.tolist()
    geometry = [mapping(geoms[0])]
    
    # Use the mask function to clip the raster array
    with rasterio.open(fn) as src:
        st_c_masked, out_transform = mask(src, geometry, crop=True, filled=True, all_touched=True)
    
    st_c_masked = np.where(st_c_masked == 0, np.nan, st_c_masked)


    return st_c_masked


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
    
    imgseg = cv2.resize(subset.squeeze(), dsize = (0,0), fx=0.1, fy=0.1)
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
    num_samples = 2 # 400 # 400 # 200
    R = 1 # 3 # 3 # 5
    num_gpus = 0.5
    num_cpus = 4
    res = SURE(tuner=True, num_samples=num_samples, model=model, R=R, 
        num_gpus=num_gpus, num_cpus=num_cpus)

    file_name = 'uhi_SURE.pkl'
    with open(file_name, 'wb') as file:
        pickle.dump(res, file)
        


    
    # u, jumps, J_grid, nrj, eps, it = model.run()
    
    # u_scaled = u / np.max(model.Y_raw, axis = -1)
    

    # plt.imsave("test.png", u)