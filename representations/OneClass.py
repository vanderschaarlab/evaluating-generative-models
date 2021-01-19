
# Copyright (c) 2021, Ahmed M. Alaa
# Licensed under the BSD 3-clause license (see LICENSE.txt)

"""
  
  ----------------------------------------- 
  One-class representations
  ----------------------------------------- 

"""

from __future__ import absolute_import, division, print_function

import numpy as np
import sys

import logging
import torch.nn as nn

if not sys.warnoptions:
    import warnings
    warnings.simplefilter("ignore")
    
from representations.networks import *  


# One-class loss functions
# ------------------------


def OneClassLoss(outputs, c): 
    
    dist   = torch.sum((outputs - c) ** 2, dim=1)
    loss   = torch.mean(dist)
    
    return loss


def SoftBoundaryLoss(outputs, R, c, nu):
    
    dist   = torch.sum((outputs - c) ** 2, dim=1)
    scores = dist - R ** 2
    loss   = R ** 2 + (1 / nu) * torch.mean(torch.max(torch.zeros_like(scores), scores))
    
    scores = dist 
    loss   = (1 / nu) * torch.mean(torch.max(torch.zeros_like(scores), scores))
    
    return loss


LossFns    = dict({"OneClass": OneClassLoss, "SoftBoundary": SoftBoundaryLoss})

# Base network
# ---------------------

class BaseNet(nn.Module):
    
    """Base class for all neural networks."""

    def __init__(self):
        
        super().__init__()
        
        self.logger  = logging.getLogger(self.__class__.__name__)
        self.rep_dim = None  # representation dimensionality, i.e. dim of the last layer

    def forward(self, *input):
        
        """Forward pass logic
        
        :return: Network output
        """
        raise NotImplementedError

    def summary(self):
        
        """Network summary."""
        
        net_parameters = filter(lambda p: p.requires_grad, self.parameters())
        params         = sum([np.prod(p.size()) for p in net_parameters])
        
        self.logger.info('Trainable parameters: {}'.format(params))
        self.logger.info(self)


def get_radius(dist:torch.Tensor, nu:float):
    
    """Optimally solve for radius R via the (1-nu)-quantile of distances."""
    
    return np.quantile(np.sqrt(dist.clone().data.float().numpy()), 1 - nu)

class OneClassLayer(BaseNet):

    def __init__(self, params=None, hyperparams=None):
        
        super().__init__()
        
        # set all representation parameters - remove these lines

        self.rep_dim        = params["rep_dim"] 
        self.input_dim      = params["input_dim"]
        self.num_layers     = params["num_layers"]
        self.num_hidden     = params["num_hidden"]
        self.activation     = params["activation"]
        self.dropout_prob   = params["dropout_prob"]
        self.dropout_active = params["dropout_active"]  
        self.loss_type      = params["LossFn"]
        
        self.device         = torch.device('cpu') # Make this an option
        
        # set up the network
        
        self.model          = build_network(network_name="feedforward", params=params) 

        # create the loss function

        self.c              = hyperparams["center"]
        self.R              = hyperparams["Radius"]
        self.nu             = hyperparams["nu"]

        self.loss_fn        = LossFns[self.loss_type]

        
    def forward(self, x):
        
        x                   = self.model(x)
        
        return x
    
    
    def fit(self, x_train, learningRate=0.01, epochs=100, warm_up_epochs=10, verbosity=True):
        
        self.epochs         = epochs
        self.learningRate   = learningRate         
        self.optimizer      = torch.optim.Adam(self.model.parameters(), lr=self.learningRate)
        
        self.X              = torch.tensor(x_train.reshape((-1, self.input_dim))).float()
        self.losses         = []
        
        for epoch in range(self.epochs):
            
            # Converting inputs and labels to Variable
            
            if torch.cuda.is_available():
                
                inputs = Variable(torch.from_numpy(x_train).cuda()).float()
            
            else:
                
                inputs = Variable(torch.from_numpy(x_train)).float()
            
            self.model.zero_grad()

            self.optimizer.zero_grad()

            # get output from the model, given the inputs
            outputs = self.model(inputs)

            # get loss for the predicted output
            
            if self.loss_type=="SoftBoundary":
                
                self.loss = self.loss_fn(outputs=outputs, R=self.R, c=self.c, nu=self.nu) 
                
            elif self.loss_type=="OneClass":
                
                self.loss = self.loss_fn(outputs=outputs, c=self.c) 
            
            l2_lambda = .5
            l2_reg    = torch.tensor(0.)
            
            for param in self.model.parameters():
                
                l2_reg += torch.norm(param)  
            
            self.loss = self.loss + l2_lambda * l2_reg 
            #self.c    = torch.mean(torch.tensor(outputs).float(), dim=0)
            
            # get gradients w.r.t to parameters
            self.loss.backward(retain_graph=True)
            self.losses.append(self.loss.detach().numpy())
        
            # update parameters
            self.optimizer.step()
            
            if (epoch >= warm_up_epochs) and (self.loss_type=="SoftBoundary"):
                
                dist   = torch.sum((outputs - self.c) ** 2, dim=1)
                #self.R = torch.tensor(get_radius(dist, self.nu))
            

            if verbosity:

                print('epoch {}, loss {}'.format(epoch, self.loss.item()))