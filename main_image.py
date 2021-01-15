# -*- coding: utf-8 -*-
"""
Created on Wed Jan 13 10:46:17 2021

@author: Boris van Breugel (bv292@cam.ac.uk)
"""

import os
import glob

import tensorflow as tf
from keras.preprocessing.image import load_img
from keras.preprocessing.image import img_to_array
from keras.applications.vgg16 import preprocess_input
from keras.models import Model

import numpy as np

from metrics.feature_distribution import feature_distribution
from metrics.compute_wd_v2 import compute_wd
from metrics.compute_identifiability import compute_identifiability
from metrics.fid import calculate_frechet_distance, fit_gaussian

from PIL import Image


#%%

def reset_weights(model):
    for layer in model.layers: 
        if isinstance(layer, tf.keras.Model):
            reset_weights(layer)
            continue
    for k, initializer in layer.__dict__.items():
        if "initializer" not in k:
            continue
      # find the corresponding variable
        var = getattr(layer, k.replace("_initializer", ""))
        var.assign(initializer(var.shape, var.dtype))
    return model


def identity_flatten(array):
    return array.flatten(array.shape[0],-1)
 
    
def remove_layer(model):
        new_input = model.input
        hidden_layer = model.layers[-2].output
        return Model(new_input, hidden_layer)   


def load_embedder(embedding):
    if embedding['model'] == 'vgg16' or embedding['model'] == 'vgg':
        model = tf.keras.applications.VGG16(include_top = True, weights='imagenet')
        model = remove_layer(model)
        model = model
        model.trainable = False
    
        
    elif embedding['model'] == 'inceptionv3' or embedding['model'] == 'inception':
        model = tf.keras.applications.InceptionV3(include_top = True, weights='imagenet')
        model = remove_layer(model)
        model.trainable = False
    
    else:
        print('Did not recognise name of embedding model. Using identity embedding instead')
        model = identity_flatten
    
    
    if embedding['randomise']:
        model = reset_weights(model)
        if embedding['dim64']:
            # removes last layer and inserts 64 output
            model = remove_layer(model)
            new_input = model.input
            hidden_layer = tf.keras.layers.Dense(64)(model.layers[-2].output)
            model = Model(new_input, hidden_layer)   
    
    return model

#%% load data and conpute activations


def load_image_batch(files,shape):
    """Convenience method for batch-loading images
    Params:
    -- files    : list of paths to image files. Images need to have same dimensions for all files.
    Returns:
    -- A numpy array of dimensions (num_images,hi, wi, 3) representing the image pixel values.
    """
    images = np.zeros((len(files),shape,shape,3))
    for i in range(len(files)):
        image = load_img(files[i], target_size=(shape,shape))
        images[i] = img_to_array(image)
    images = preprocess_input(images)

    images = tf.convert_to_tensor(images)
    return images

def load_all_images(files):
    """Convenience method for batch-loading images
    Params:
    -- files    : list of paths to image files. Images need to have same dimensions for all files.
    Returns:
    -- A numpy array of dimensions (num_images,hi*wi)
    """
    images = np.zeros((len(files),28**2))
    for i in range(len(files)):
        image = np.array(Image.open(files[i])).reshape(1,-1)
        images[i] = image
    images = preprocess_input(images)
    return images




def get_activations_from_files(files, embedder, batch_size=None, verbose=False):
    """Calculates the activations of the pool_3 layer for all images.

    Params:
    -- files      : list of paths to image files. Images need to have same dimensions for all files.
    -- embedding        : embedding type (Inception, VGG16, None)
    -- batch_size  : the images numpy array is split into batches with batch size
                     batch_size. A reasonable batch size depends on the disposable hardware.
    -- verbose    : If set to True and parameter out_step is given, the number of calculated
                     batches is reported.
    Returns:
    -- A numpy array of dimension (num images, embedding_size) that contains the
       activations of the given tensor when feeding e.g. inception with the query tensor.
    """
    
    n_imgs = len(files)
    
    if batch_size is None:
        batch_size = n_imgs
    elif batch_size > n_imgs:
        print("warning: batch size is bigger than the data size. setting batch size to data size")
        batch_size = n_imgs
    n_batches = n_imgs//batch_size + 1
    

    pred_arr = np.empty((n_imgs,embedder.output.shape[-1]))
    input_shape = embedder.input.shape[1]
    
    for i in range(n_batches):
        if verbose:
            print("\rPropagating batch %d/%d" % (i+1, n_batches), end="", flush=True)
        start = i*batch_size
        if start+batch_size < n_imgs:
            end = start+batch_size
        else:
            end = n_imgs
        
 
        batch = load_image_batch(files[start:end], input_shape)
        
        pred = embedder(batch)
        pred_arr[start:end] = pred.numpy()
        del batch #clean up memory
        
    if verbose:
        print(" done")
    
    return pred_arr

    


#%% main

def main(paths, embedding, load_act=True, save_act=True, verbose = False):
    ''' Calculates the FID of two paths. '''
    
    print('#### Embedding info',embedding, '#####')
    activations = []
    m = []
    s = []
    fid_values = {}
    # Load embedder function
    if embedding is not None:
        embedder = load_embedder(embedding)
    
    # Loop through datasets
    for path_index, path in enumerate(paths):
        print('============ Path', path, '============')
        # Check if folder exists
        if not os.path.exists(path):
            raise RuntimeError("Invalid path: %s" % path)
        # Don't embed data if no embedding is given 
        if embedding is None:
            files = list(glob.glob(os.path.join(path,'**/*.jpg'),recursive=True)) + list(glob.glob(os.path.join(path,'**/*.png'),recursive=True)) 
            act = load_all_images(files)    
    
        else:
            act_filename = f'{path}/act_{embedding["model"]}_{embedding["dim64"]}_{embedding["randomise"]}'
            # Check if embeddings are already available
            if load_act and os.path.exists(f'{act_filename}.npz'):
                print('Loaded activations from', act_filename)
                data = np.load(f'{act_filename}.npz',allow_pickle=True)
                act, _ = data['act'], data['embedding']
            # Otherwise compute embeddings
            else:
                if load_act:
                    print('Could not find activation file', act_filename)
                print('Calculating activations')
                files = list(glob.glob(os.path.join(path,'**/*.jpg'),recursive=True)) + list(glob.glob(os.path.join(path,'**/*.png'),recursive=True)) 
                act = get_activations_from_files(files, embedder, batch_size=64*8, verbose=verbose)
                
                # Save embeddings
                if save_act:
                    np.savez(f'{act_filename}', act=act,embedding=embedding)
                    
        
        activations.append(act)            
    
        
        # Frechet distance statistics
        m_i, s_i = fit_gaussian(act)
        m.append(m_i)
        s.append(s_i)
        
        if path_index!=0:
            # (0) Frechet distance
            fid_value = calculate_frechet_distance(m[0],s[0],m[path_index],s[path_index])
            fid_values[path_index] = fid_value
            print('Frechet distance', fid_value)
            print('Frechet distance/dim', fid_value/act.shape[-1])
            
            # (1) Marginal distributions
            #print("Start computing marginal feature distributions")
            #feat_dist = feature_distribution(activations[0], act)
            #print("Finish computing feature distributions")
            #print(feat_dist)
            
            # (2) Wasserstein Distance (WD)
            print("Start computing Wasserstein Distance")
            params = dict()
            params["iterations"] = 10000
            params["h_dim"] = 30
            params["z_dim"] = 10
            params["mb_size"] = 128
            
            wd_measure = compute_wd(activations[0], act, params)
            print("WD measure: " + str(wd_measure))
            
            
            # (3) Identifiability 
            print("Start computing identifiability")
            identifiability = compute_identifiability(activations[0], act)
            print("Identifiability measure: " + str(identifiability))
        
    return activations, fid_values




if __name__ == '__main__':
    os.environ['CUDA_VISIBLE_DEVICES'] = '0'
    
    #for embed in ['inceptionv3','vgg','identity']:
    methods = ['WGAN-GP','DCGAN','VAE','CGAN', 'ADS-GAN']
    load_act = True
    save_act = True
    nul_path = ['data/mnist/original/testing']
    other_paths = [f'data/mnist/synth/{method}' for method in methods]
    paths = nul_path + other_paths
    embeddings = []
#    embeddings.append(None)
    embeddings.append({'model':'inceptionv3',
                 'randomise': False, 'dim64': False})
    embeddings.append({'model':'vgg16',
                 'randomise': False, 'dim64': False})
    embeddings.append({'model':'vgg16',
                 'randomise': True, 'dim64': False})
    embeddings.append({'model':'vgg16',
                 'randomise': True, 'dim64': True})
    
        
    for embedding in embeddings:
        output = main(paths, embedding, load_act, save_act,verbose=True)
        activations, fid_values = output
    