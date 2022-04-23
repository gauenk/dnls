
# -- linalg --
import torch as th
import numpy as np
from einops import rearrange

# -- python-only numba --
import math
from numba import njit,cuda

def run(patches,nlDists,nlInds,vid=None,wvid=None,shape=None):

    # -- misc --
    device = patches.device

    # -- allocate videos --
    if vid is None: vid = allocate_vid(shape,device)
    if wvid is None: wvid = allocate_vid(shape,device)

    # -- exec gather --
    numba_launcher(vid,wvid,patches,nlDists,nlInds)

    return vid,wvid

def allocate_vid(shape,device):
    vid = th.zeros(shape,device=device,dtype=th.float32)
    return vid

def numba_launcher(vid,wvid,patches,nlDists,nlInds):

    # -- numbify the torch tensors --
    vid_nba = vid.cpu().numpy()
    wvid_nba = wvid.cpu().numpy()
    patches_nba = patches.cpu().numpy()
    nlDists_nba = nlDists.cpu().numpy()
    nlInds_nba = nlInds.cpu().numpy()

    # -- exec --
    numba_gather(vid_nba,wvid_nba,patches_nba,nlDists_nba,nlInds_nba)

    # -- to device --
    device = vid.device
    vid_nba = th.from_numpy(vid_nba).to(device)
    wvid_nba = th.from_numpy(wvid_nba).to(device)

    # -- fill --
    vid[...] = vid_nba[...]
    wvid[...] = wvid_nba[...]

@njit
def numba_gather(vid,wvid,patches,vals,inds):

    # -- valid index --
    def valid_ind(ti,hi,wi):
        if ti == -1: return False
        if hi == -1: return False
        if wi == -1: return False
        return True

    # -- shape --
    _,_,pt,_,ps,ps = patches.shape
    nframes,color,height,width = vid.shape
    chw = color*height*width
    hw = height*width
    bsize,npatches,_ = inds.shape # "npatches" _must_ be from "inds"
    npatches_f = 1.*npatches
    psHalf = ps//2
    psHalf2 = psHalf * psHalf

    for bi in range(bsize):
        for ni in range(npatches):

            # -- unpack inds --
            t0 = inds[bi,ni,0]
            h0 = inds[bi,ni,1]
            w0 = inds[bi,ni,2]
            if not valid_ind(t0,h0,w0): continue

            # -- fill --
            for pk in range(pt):
                for pi in range(ps):
                    for pj in range(ps):
                        t1 = (t0+pk)# % nframes
                        h1 = (h0+pi-psHalf)# % height
                        w1 = (w0+pj-psHalf)# % width

                        # -- boundary --
                        if t1 < 0 or t1 >= nframes: continue
                        if h1 < 0 or h1 >= height: continue
                        if w1 < 0 or w1 >= width: continue

                        # -- weight --
                        pleft = (pi - psHalf)**2/psHalf2
                        pright = (pj - psHalf)**2/psHalf2
                        pdist = pleft + pright
                        weight = 1.#math.exp(-10000.*pdist)

                        # -- fill --
                        for ci in range(color):
                            gval = patches[bi,ni,pk,ci,pi,pj]
                            vid[t1,ci,h1,w1] += weight * gval
                            wvid[t1,ci,h1,w1] += weight
