
import numpy as np
import torch
from typing import Tuple, List, Dict
from utils import * 
import cv2
from matplotlib import pyplot as plt
from sklearn.cluster import KMeans
from scipy.spatial import cKDTree


class FDD():
    def __init__(self, Y : np.array, X : np.array, pick_nu : str="kmeans", level : int=16, 
                 lmbda : float=1, nu : float=0.01, iter : int=1000, tol : float=5e-5, rectangle : bool=False, 
                 qtile : float=0.05, image : bool=False, grid : bool=False, resolution : float=None) -> None:

        self.device = self.setDevice()
        torch.set_grad_enabled(False)
        
        self.Y_raw = Y.copy() # retain original data
        self.X_raw = X.copy()
        self.Y = Y.copy() # arrays I'll pass to PyTorch
        self.X = X.copy()
        
        self.image = image
        self.grid = grid
        self.level = level
        self.lmbda = lmbda
        self.iter = iter
        self.tol = tol
        self.rectangle = rectangle
        self.qtile = qtile
        self.resolution = resolution
        
        self.normalizeData() # scale data to unit hypercube
        
        if self.image:
            self.grid_y = np.expand_dims(Y.copy(), -1)
            self.grid_y = self.grid_y / np.max(self.grid_y) - np.min(self.grid_y) # TODO allow for 3d and color images
            X_temp = X.copy() / np.max(X.reshape((-1, X.shape[-1])), axis = 0)
            self.grid_x, self.grid_x_og = X_temp.copy(), X_temp.copy()
            self.resolution = 1 / np.max(self.grid_y.shape)
        else:
            self.castDataToGrid()
        
        # if pick_nu == "auto":
        #     u_diff = self.forward_differences(self.grid_y, D = len(self.grid_y.shape))
        #     u_diff = u_diff / self.resolution # scale FD by side length
        #     u_norm = np.linalg.norm(u_diff, axis = 0, ord = 2) # 2-norm
        #     self.nu = self.pickKMeans(u_norm)
        # else:
        self.nu = nu
        self.pick_nu = pick_nu
        
        self.model = torch.jit.load("src/FDD/scripted_primal_dual.pt", map_location = self.device)
        
        
        self.model = self.model.to(self.device)
        # TODO: exclude duplicate points (there shouldnt be any cause the variables are assumed to be continuous but anyway)
        

        
    def setDevice(self):
        if torch.cuda.is_available(): # cuda gpus
            device = torch.device("cuda")
            #torch.cuda.set_device(int(gpu_id))
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
        elif torch.backends.mps.is_available(): # mac gpus
            device = torch.device("mps")
        elif torch.backends.mkl.is_available(): # intel cpus
            device = torch.device("mkl")
        torch.set_grad_enabled(True)
        return device
    
    def normalizeData(self):
        
        min_y = np.min(self.Y, axis = 0)
        min_x = np.min(self.X, axis = 0)
        
        self.Y = self.Y - min_y # start at 0
        self.X = self.X - min_x
        
        max_y = np.max(self.Y, axis = 0)
        if self.rectangle: # retain proportions between data -- should be used when units are identical along all axes
            max_x = np.max(self.X)
            self.Y = self.Y / max_y
            self.X = self.X / max_x
        else: # else scale to square
            max_x = np.max(self.X, axis = 0)
            self.Y = self.Y / max_y
            self.X = self.X / max_x
    
    def castDataToGridPoints(self):
        
        n = self.Y.shape[0]
        
        # calculate 0.5% quantile of distances between points
        # if data is large, use a random sample of 1000 points to calculate quantile
        if n > 1000:
            idx = np.random.permutation(n)
            idx = idx[:1000]
            X_sample = self.X[idx,:]
            distances = np.sqrt(np.sum((X_sample[:,None,:] - X_sample[None,:,:])**2, axis = 2))

        else:   
            distances = np.sqrt(np.sum((self.X[:,None,:] - self.X[None,:,:])**2, axis = 2))
        np.fill_diagonal(distances, 1) # remove self-comparisons
        distances = np.min(distances, axis = 0) # get closest point for each point
        qile = np.quantile(distances, self.qtile) # get 5% quantile
        
        # pythagoras
        
        if self.grid:
            self.resolution = qile
        else:
            self.resolution = 2*  qile / np.sqrt(2) # on average, points fall in center of grid cell, then use Pythagoras to get resolution
        
        xmax = np.max(self.X, axis = 0)
        
        # set up grid
        grid_x = np.meshgrid(*[np.arange(0, xmax[i], self.resolution) for i in range(self.X.shape[1])])
        grid_x = np.stack(grid_x, axis = -1)
        if self.Y.ndim > 1: # account for vector-valued outcomes
            grid_y = np.zeros(list(grid_x.shape[:-1]) + [self.Y.shape[1]])
        else:
            grid_y = np.zeros(list(grid_x.shape[:-1]))
        grid_x_og = np.empty(list(grid_x.shape[:-1]), dtype = object) # assign original x values as well for later

        # find closest data point for each point on grid and assign value
        # Iterate over the grid cells
        it = np.nditer(grid_x[...,0], flags = ['multi_index'])
        for x in it:
            distances = np.linalg.norm(self.X - grid_x[it.multi_index], axis=1, ord = 2)
            # Find the closest seed
            closest_seed = np.argmin(distances)
            # Assign the value of the corresponding data point to the grid cell
            grid_y[it.multi_index] = self.Y[closest_seed] #.min()

            # assign original x value
            grid_x_og[it.multi_index] = tuple(self.X_raw[closest_seed,:])
        
        if self.Y.ndim == 1:
            grid_y = grid_y.reshape(grid_y.shape + (1,))

        self.grid_x_og = grid_x_og
        self.grid_x = grid_x
        self.grid_y = grid_y
        
        
    def castDataToGridSmooth(self):
        
        n = self.Y.shape[0]
        
        if self.resolution is None:
            self.resolution = 1/int(np.sqrt(n)) # int so we get a natural number of grid cells
        
        xmax = np.max(self.X, axis = 0)
        
        # set up grid
        grid_x = np.meshgrid(*[np.arange(0, xmax[i], self.resolution) for i in range(self.X.shape[1])])
        grid_x = np.stack(grid_x, axis = -1)
        if self.Y.ndim > 1: # account for vector-valued outcomes
            grid_y = np.zeros(list(grid_x.shape[:-1]) + [self.Y.shape[1]])
        else:
            grid_y = np.zeros(list(grid_x.shape[:-1]))
        grid_x_og = np.empty(list(grid_x.shape[:-1]), dtype = object) # assign original x values as well for later
        
        # Get the indices of the grid cells for each data point
        indices = [(np.clip(self.X[:, i] // self.resolution, 0, grid_y.shape[i] - 1)).astype(int) for i in range(self.X.shape[1])]
        indices = np.array(indices).T

        # Create a count array to store the number of data points in each cell
        counts = np.zeros_like(grid_y)

        # Initialize grid_x_og with empty lists
        for index in np.ndindex(grid_x_og.shape):
            grid_x_og[index] = []
        

        # Iterate through the data points and accumulate their values in grid_y and grid_x_og
        for i, index_tuple in enumerate(indices):
            index = tuple(index_tuple)
            if np.all(index < grid_y.shape):
                # add  Y value to grid cell
                grid_y[index] += self.Y[i]
                counts[index] += 1
                grid_x_og[index].append(self.X[i])
        
        

        # Divide the grid_y by the counts to get the average values
        grid_y = np.divide(grid_y, counts, where=counts != 0, out=grid_y)

        # Find the closest data point for empty grid cells
        empty_cells = np.where(counts == 0)
        empty_cell_coordinates = np.vstack([empty_cells[i] for i in range(self.X.shape[1])]).T * self.resolution
        if empty_cell_coordinates.size > 0:
            tree = cKDTree(self.X)
            _, closest_indices = tree.query(empty_cell_coordinates, k=1)
            closest_Y_values = self.Y[closest_indices]

            # Assign the closest data point values to the empty grid cells
            grid_y[empty_cells] = closest_Y_values
        
        # add an extra "channel" dimension if we have a scalar outcome
        if self.Y.ndim == 1:
            grid_y = grid_y.reshape(grid_y.shape + (1,))

        self.grid_x_og = grid_x_og
        self.grid_x = grid_x
        self.grid_y = grid_y
        
        
    def castDataToGrid(self):
        
        self.castDataToGridSmooth()
        

        
    @staticmethod
    def interpolate(k, uk0, uk1, l):
        return (k + (0.5 - uk0) / (uk1 - uk0)) / l

    def isosurface(self, u):

        mask = (u[...,:-1] > 0.5) & (u[...,1:] <= 0.5)
        # Find the indices of the first True value along the last dimension, and set all the following ones to False
        mask[..., 1:] = (mask[..., 1:]) & (mask.cumsum(-1)[...,:-1] < 1)

        uk0 = u[...,:-1][mask]
        uk1 = u[...,1:][mask]
        
        # get the indices of the last dimension where mask is True
        k = np.where(mask == True)[-1] + 1
        
        h_img = self.interpolate(k, uk0, uk1, self.level).reshape(self.grid_y.shape[:-1])
        
        return h_img
    
    def k_means_boundary(self):
        # histogram of gradient norm
        test = np.linalg.norm(forward_differences(mIn, D = len(mIn.shape)), axis = 0)
        out = plt.hist(test)

        X1 = np.tile(out[1][1:], out[0].shape[0])
        X2 = out[0].reshape(-1,1).squeeze(1)
        Z = np.stack([X1, X2], axis = 1)


        kmeans = KMeans(n_clusters=2, random_state=0).fit(Z)
        nu = X1[kmeans.labels_ == 1].max()
        
    def boundaryGridToData(self, J_grid, u):
        # get the indices of the J_grid where J_grid is 1
        

        k = np.array(np.where(J_grid == 1))

        # Store the average points
        Y_jumpfrom = []
        Y_jumpto = []
        Y_jumpsize = []
        Y_boundary = []
        
        # scale u back to get correct jump sizes
        u_scaled = u * np.max(self.Y_raw, axis = 0)

        # Iterate over the boundary points
        for i in range(k.shape[1]):
            
            origin_points = []
            dest_points = []

            # Get the coordinates of the current boundary point
            point = k[:, i]

            # Initialize a list to store the neighboring hypervoxels
            neighbors = []

            # Iterate through all dimensions
            for d in range(k.shape[0]):

                # Calculate the down-right neighbor along the current dimension
                neighbor = point.copy()
                if neighbor[d] < J_grid.shape[d] - 1:
                    neighbor[d] += 1

                    # Check if the neighbor is not a boundary point
                    if J_grid[tuple(neighbor)] != 1:
                        neighbors.append(neighbor)

            # Check if there are any valid neighbors
            if neighbors:
                
                # origin_points
                origin_points = self.grid_x_og[tuple(point)]
                Yjumpfrom = self.grid_y[tuple(point)]
                if len(origin_points) == 0:
                    origin_points = self.grid_x[tuple(point)]
                    
                # jumpfrom point
                origin_points = np.stack(origin_points).squeeze()
                jumpfrom = np.mean(origin_points, axis = 0)

                # jumpto point
                for i in range(len(neighbors)):
                    
                
                    pointslist = [self.grid_x_og[tuple(neighbors[i])] for i in range(len(neighbors))]
                
                if not np.stack(pointslist).any():
                    pointslist = [self.grid_x[tuple(neighbors[i])] for i in range(len(neighbors))]
                
                Yjumpto = np.mean([self.grid_y[tuple(neighbors[i])] for i in range(len(neighbors))])
                dest_points = np.stack(pointslist).squeeze()
                jumpto = np.mean(dest_points, axis = 0)
                
                # append to lists
                Y_boundary.append((jumpfrom + jumpto) / 2)
                Y_jumpfrom.append(Yjumpfrom)
                Y_jumpto.append(Yjumpto)
                Y_jumpsize.append(Yjumpto - Yjumpfrom)
                
                
                
                

        # Convert the result list to a numpy array
        avg_points = np.array(avg_points)

        
        
        
        
        ##############################
        k = np.array(np.where(J_grid == 1))
                
        distances = [] # TODO: can't jump to another boundary point
        k_shifts = []

        
        for d in range(k.shape[0]):
            
            # take the forward difference along one dimension
            k_shift = k.copy()
            k_shift[d] = np.where(k_shift[d] == J_grid.shape[d] - 1, # if at the edge of the domain, don't shift
                                  k_shift[d], k_shift[d] + 1) 
            k_shifts.append(k_shift)
            
            # find all columns in k_shift that are also in k, we don't want to jump to another boundary point
            matching_rows = np.all(k_shift.T[:, np.newaxis] == k.T, axis=-1).any(axis=1)
            
            
            
            
        distances = np.array(distances)
        distances = np.where(distances == 0, np.inf, distances)
        
        # filter out columns where all the elements are inf, these will be "thick" boundary points
        idx = ~np.all(distances == np.inf, axis=0)
        distances = distances[:, idx]
        k_shifts = np.array(k_shifts)
        k_shifts = k_shifts[:, :, idx]
        k = k[:,idx]
        idx = np.argmin(distances, axis = 0)
        
        closest_points = k_shifts[idx, :, np.arange(k_shifts.shape[2])] # these are the coordinates of the jump to points
        midpoints = (k.T + closest_points) / 2 # these are the estimated boundary points
        
        #closest_points = ((closest_points / self.grid_x.shape[:-1])) 

        # get jumpto points
        # matching_rows = np.all(self.X_raw[:, np.newaxis] == closest_points, axis=-1)
        # matching_indices = np.where(matching_rows)[0]
        
        # first scale u back
        u_scaled = u *  np.max(self.Y_raw, axis = 0)
        
        # get the points of self.grid_x_og with the index (x,y) for each row [x,y] in closest_points
        closest_x = np.array([self.grid_x_og[tuple(i)] for i in closest_points])
        Y_jumpto =  np.array([u_scaled[tuple(i)] for i in closest_points])
        
        # get jumpfrom points
        closest_x_shift = np.array([self.grid_x_og[tuple(i)] for i in k.T])
        Y_jumpfrom =  np.array([u_scaled[tuple(i)] for i in k.T])
        
        # jump size
        jumpsize = Y_jumpto - Y_jumpfrom
        
        # create named array to return
        rays = [midpoints[:,d] for d in range(midpoints.shape[1])] + [Y_jumpfrom, Y_jumpto, jumpsize]
        names = ["X_" + str(d) for d in range(midpoints.shape[1])] + ["Y_jumpfrom", "Y_jumpto", "Y_jumpsize"]
        jumps = np.core.records.fromarrays(rays, names=names)
        
        return jumps
    
    def pickKMeans(self, u_norm):
        plt.ioff()  # Turn off interactive mode to prevent the figure from being displayed
        out = plt.hist(u_norm)
        plt.close()  # Close the figure to free up memory

        X1 = np.tile(out[1][1:], out[0].shape[0])
        X2 = out[0].reshape(-1,1).squeeze(1)
        Z = np.stack([X1, X2], axis = 1)

        # the histogram is "bimodal" (one large cluster and a bunch of smaller ones), so we use k-means to find the edge of the first "jump" cluster
        # TODO: averages instead of closest points
        kmeans = KMeans(n_clusters=2, random_state=0, n_init = "auto").fit(Z)
        
        nu = X1[kmeans.labels_ == 1].max()
        return nu
        
    def boundary(self, u):
        
        u_diff = self.forward_differences(u, D = len(u.shape))
        u_diff = u_diff # / self.resolution # scale FD by side length
        u_norm = np.linalg.norm(u_diff, axis = 0, ord = 2) # 2-norm

        if self.pick_nu == "kmeans":
            nu = self.pickKMeans(u_norm)
        else:
            nu = np.sqrt(self.nu)
        
        # find the boundary on the grid by comparing the gradient norm to the threshold
        J_grid = (u_norm >= nu).astype(int)
        
        ## find the boundary on the point cloud
        jumps = self.boundaryGridToData(J_grid, u)
        
        # test_grid = np.zeros(self.grid_y.shape)
        # for row in jumps:
        #     test_grid[tuple(row)[:-2]] = 1

        return (J_grid, jumps)
    
    #def treatmentEffects(self, u, J):
        
        
    def forward_differences(self, ubar, D : int):

        diffs = []

        for dim in range(int(D)):
            #zeros_shape = torch.jit.annotate(List[int], [])
            zeros_shape = list(ubar.shape)
            zeros_shape[dim] = 1
            # for j in range(ubar.dim()): 
            #     if j == dim:
            #         zeros_shape.append(1)
            #     else:
            #         zeros_shape.append(ubar.shape[j])
            zeros = np.zeros(zeros_shape)
            diff = np.concatenate((np.diff(ubar, axis=dim), zeros), axis=dim)
            diffs.append(diff)

        # Stack the results along a new dimension (first dimension)
        u_star = np.stack(diffs, axis=0)

        return u_star
        
    def run(self):
        
        f = torch.tensor(self.grid_y, device = self.device, dtype = torch.float32)
        repeats = torch.tensor(self.iter, device = self.device, dtype = torch.int32)
        level = torch.tensor(self.level, device = self.device, dtype = torch.int32)
        lmbda = torch.tensor(self.lmbda, device = self.device, dtype = torch.float32)
        nu = torch.tensor(self.nu, device = self.device, dtype = torch.float32)
        tol = torch.tensor(self.tol, device = self.device, dtype = torch.float32)
        
        results = self.model(f, repeats, level, lmbda, nu, tol)
        
        v, nrj, eps, it = results
        v = v.cpu().detach().numpy()
        nrj = nrj.cpu().detach().numpy()
        eps = eps.cpu().detach().numpy()
        
        u = self.isosurface(v) 
        
        J_grid, jumps = self.boundary(u)
        
        # renormalize u
        
        return (u, jumps, J_grid, nrj, eps, it)
        

        
        
        
if __name__ == "__main__":
    def setDevice():
        if torch.cuda.is_available(): # cuda gpus
            device = torch.device("cuda")
            #torch.cuda.set_device(int(gpu_id))
            torch.set_default_tensor_type('torch.cuda.FloatTensor')
        elif torch.backends.mps.is_available(): # mac gpus
            device = torch.device("mps")
        elif torch.backends.mkl.is_available(): # intel cpus
            device = torch.device("mkl")
        torch.set_grad_enabled(True)
        return device

    # detect GPU device and set it as default
    dev = setDevice()
    g = DeviceMode(torch.device(dev))
    g.__enter__()
    
    
    # #------ test 1

    # image = "resources/images/marylin.png"
    # mIn = cv2.imread(image, (0))
    # mIn = mIn.astype(np.float32)
    # mIn /= 255
    
    
    # Y = mIn.copy().flatten()
    # #Y = np.stack([Y, Y], axis = 1)
    # # get labels of grid points associated with Y values in mIn
    # #X = np.stack(np.meshgrid(*[np.arange(Y.shape[1]), np.arange(Y.shape[0])]), axis = -1)
    # X = np.stack([np.tile(np.arange(0, mIn.shape[0], 1), mIn.shape[1]), np.repeat(np.arange(0, mIn.shape[0], 1), mIn.shape[1])], axis = 1)
    
    # # reshuffle Y and X in the same way so that it resembles normal data
    # idx = np.random.permutation(Y.shape[0])
    # Y = Y[idx]
    # X = X[idx]
            
    # def forward_differences(ubar, D : int):

    #     diffs = []

    #     for dim in range(int(D)):
    #         #zeros_shape = torch.jit.annotate(List[int], [])
    #         zeros_shape = list(ubar.shape)
    #         zeros_shape[dim] = 1
    #         # for j in range(ubar.dim()): 
    #         #     if j == dim:
    #         #         zeros_shape.append(1)
    #         #     else:
    #         #         zeros_shape.append(ubar.shape[j])
    #         zeros = np.zeros(zeros_shape)
    #         diff = np.concatenate((np.diff(ubar, axis=dim), zeros), axis=dim)
    #         diffs.append(diff)
    #                 # Stack the results along a new dimension (first dimension)
    #     u_star = np.stack(diffs, axis=0)

    #     return u_star
    
    # def boundary(u, nu):
    #     u_diff = forward_differences(u, D = len(u.shape))
    #     u_norm = np.linalg.norm(u_diff, axis = 0, ord = 2) # 2-norm
    #     return (u_norm >= np.sqrt(nu)).astype(int)
    

    # # histogram of gradient norm
    # test = np.linalg.norm(forward_differences(mIn, D = len(mIn.shape)), axis = 0)
    # out = plt.hist(test)

    # X1 = np.tile(out[1][1:], out[0].shape[0])
    # X2 = out[0].reshape(-1,1).squeeze(1)
    # Z = np.stack([X1, X2], axis = 1)

    # from sklearn.cluster import KMeans

    # kmeans = KMeans(n_clusters=2, random_state=0).fit(Z)
    # nu = X1[kmeans.labels_ == 1].max()

    # model = FDD(Y, X, level = 16, lmbda = 0.5, nu = 0.001, iter = 10000, tol = 5e-5, 
    #             image=False, pick_nu = "kmeans")
    # model.lmbda = 5
    # u, jumps, J_grid, nrj, eps, it = model.run()
    # cv2.imwrite("result.png",u*255)
    
    # model.pick_nu = "kmeans"
    # J_grid, jumps = model.boundary(u)
    
    # plt.imshow(u)
    # plt.show()
    
    # plt.imshow(J_grid)
    # plt.show()
    
    # # plot image with boundary
    # plt.imshow(u, cmap = "gray")
    # test = J_grid.copy().astype(np.float32)
    # test[test == 0] = np.nan
    # plt.imshow(test, cmap='autumn', interpolation='none')
    # plt.show()
    # plt.savefig("resources/images/marylin_segmented.png")

    # # histogram of gradient norm

    # test = np.linalg.norm(forward_differences(u, D = len(u.shape)), axis = 0)
    # out = plt.hist(test)
    # #plt.show()
    # plt.savefig("resources/images/hist.png")

    # X = np.tile(out[1][1:], out[0].shape[0])
    # Y = out[0].reshape(-1,1).squeeze(1)
    # Z = np.stack([X, Y], axis = 1)

    # from sklearn.cluster import KMeans

    # kmeans = KMeans(n_clusters=2, random_state=0).fit(Z)
    # nu = X[kmeans.labels_ == 1].max()

    # # get new boundary
    # J_new = boundary(u, nu = nu**2) # the squared is just cause we're taking the square root

    # plt.imshow(J_new)

    # # plt.hist(test.reshape(-1,1)[kmeans.labels_ == 2], bins = 100)

        
    # # from pomegranate import  *

    # # model = GeneralMixtureModel.from_samples(NormalDistribution, n_components=2, X=test.reshape(-1,1))
    # # labels = model.predict(test.reshape(-1,1))

    # # plt.hist(test.reshape(-1,1)[labels == 0], bins = 100)

    # # plt.hist(test.reshape(-1,1),  bins = 500)
    # # plt.ylim(0,5)
    
    
    
    # #------- test2
    
    # Generate some random data points from a discontinuous function
    np.random.seed(0)
    data = np.random.rand(1000, 2) # draw 1000 2D points from a uniform

    # Create the grid
    # Define the grid dimensions and resolution
    xmin, xmax = 0, 1
    ymin, ymax = 0, 1
    resolution = 0.01 # 100 by 100 grid
    x, y = np.meshgrid(np.arange(xmin, xmax, resolution), np.arange(ymin, ymax, resolution))
    grid = np.dstack((x, y))
    grid_f = np.zeros(grid.shape[:2])

    def f(x,y):
        temp = np.sqrt((x-1/2)**2 + (y-1/2)**2)
        if temp < 1/4:
            return temp
        else:
            return temp + 1/8

    # Compute the function values on the grid
    for i in range(grid.shape[0]):
        for j in range(grid.shape[1]):
            grid_f[i, j] = f(grid[i, j][0], grid[i, j][1])
            
    # now sample the function values on the data points
    grid_sample = np.zeros((data.shape[0],1))
    for i in range(data.shape[0]):
            grid_sample[i] = f(data[i,0], data[i,1])

    X = data.copy()
    Y = grid_sample.copy().flatten()
    # and run the FDD command
    model = FDD(Y, X, level = 16, lmbda = 10, nu = 0.001, iter = 5000, tol = 5e-5, qtile = 0.1)
    u, jumps, J_grid, nrj, eps, it = model.run()

    # plt.imshow(J_grid)
    # plt.show()


        

        