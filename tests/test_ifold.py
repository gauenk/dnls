
# -- python --
import sys

# -- data mgnmt --
from pathlib import Path
from easydict import EasyDict as edict

# -- testing --
import unittest,pytest

# -- linalg --
import torch as th
import numpy as np
from einops import rearrange,repeat

# -- dnls --
import dnls

# -- meshgrid --
import cache_io

# -- test func --
from torch.nn.functional import fold,unfold,pad
from torchvision.transforms.functional import center_crop

# -- paths --
SAVE_DIR = Path("./output/tests/")

def print_gpu_stats(gpu_bool,note=""):
    if gpu_bool:
        gpu_max = th.cuda.memory_allocated()/(1024**3)
        print("[%s] GPU Max: %2.4f" % (note,gpu_max))

def pytest_generate_tests(metafunc):
    seed = 123
    th.manual_seed(seed)
    np.random.seed(seed)
    # test_lists = {"ps":[3],"stride":[1],"dilation":[1],
    #               "top":[2],"btm":[62],"left":[2],"right":[62]}
    # test_lists = {"ps":[3],"stride":[1],"dilation":[1],
    #               "top":[3],"btm":[57],"left":[7],"right":[57]}
    # test_lists = {"ps":[3],"stride":[2],"dilation":[2],
    #               "top":[3],"btm":[57],"left":[7],"right":[57]}
    test_lists = {"ps":[3,7],"stride":[1,2,3,4,5],"dilation":[1,2,3,4,5],
                  "top":[1,11],"btm":[50,57],"left":[3,7],"right":[57,30]}
    for key,val in test_lists.items():
        if key in metafunc.fixturenames:
            metafunc.parametrize(key,val)
#
# -- Test Against Pytorch.nn.fold --
#

# @pytest.mark.skip(reason="too long right now")
def test_nn(ps,stride,dilation,top,btm,left,right):

    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    ws,wt = 10,0

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device).contiguous()
    flow = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- image params --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    nframes,height,width = t,h,w
    vshape = vid.shape

    # -- sub square --
    coords = [top,left,btm,right]
    sq_h = coords[2] - coords[0]
    sq_w = coords[3] - coords[1]

    # -- batching info --
    npix = t * h * w
    nh = (sq_h-1)//stride+1
    nw = (sq_w-1)//stride+1
    qTotal = t * nh * nw
    qSize = qTotal
    nbatches = (qTotal-1) // qSize + 1

    # -- exec fold fxns --
    scatter_nl = dnls.scatter.ScatterNl(ps,pt,dilation=dil,exact=True)
    fold_nl = dnls.ifold.iFold(vshape,coords,stride=stride,dilation=dil)

    # -- patches for ifold --
    index = 0
    queryInds = dnls.utils.inds.get_iquery_batch(index,qSize,stride,
                                                 coords,t,device)
    nlDists,nlInds = dnls.simple.search.run(vid,queryInds,flow,k,
                                            ps,pt,ws,wt,chnls,
                                            stride=stride,dilation=dil)
    assert th.sum(queryInds - nlInds[:,0]) < 1e-10
    patches_nl = scatter_nl(vid,nlInds)
    patches_nn = patches_nl.clone()
    patches_nn = patches_nn.requires_grad_(True)
    patches_nl = patches_nl.requires_grad_(True)

    #
    # -- test logic --
    #

    # -- run forward --
    top,left,btm,right = coords
    vid_nn,_ = run_fold(patches_nn,t,sq_h,sq_w,stride,dil)
    vid_nl = fold_nl(patches_nl,0)[:,:,top:btm,left:right]

    # -- run backward --
    vid_grad = th.randn_like(vid_nl)
    th.autograd.backward(vid_nn,vid_grad)
    th.autograd.backward(vid_nl,vid_grad)

    # -- check forward --
    delta = vid_nn - vid_nl
    error = th.sum(delta**2).item()
    assert error < 1e-10

    # -- check backward --
    grad_nn = patches_nn.grad
    grad_nl = patches_nl.grad

    # -- rearrange --
    shape_str = '(t h w) 1 1 c ph pw -> t c h w ph pw'
    grad_nn = rearrange(grad_nn,shape_str,t=t,h=nh)
    grad_nl = rearrange(grad_nl,shape_str,t=t,h=nh)

    # -- check backward --
    error = th.sum((grad_nn - grad_nl)**2).item()
    assert error < 1e-10

    # -- clean-up --
    th.cuda.empty_cache()
    del vid,flow
    del vid_nn,vid_nl
    del patches_nl,patches_nn
    del grad_nn,grad_nl,vid_grad
    del queryInds,nlDists,nlInds
    th.cuda.empty_cache()

#
# -- Test a Batched Ours Against Pytorch.nn.fold --
#

# @pytest.mark.skip(reason="too long right now")
def test_batched(ps,stride,dilation,top,btm,left,right):

    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    ws,wt = 10,0

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    exact = True
    gpu_stats = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device).contiguous()
    flow = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)
    print_gpu_stats(gpu_stats,"post-io")

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape

    # -- sub square --
    coords = [top,left,btm,right]
    sq_h = coords[2] - coords[0]
    sq_w = coords[3] - coords[1]

    # -- batching info --
    npix = t * h * w
    nh = (sq_h-1)//stride+1
    nw = (sq_w-1)//stride+1
    qTotal = t * nh * nw
    qSize = 512
    nbatches = (qTotal-1) // qSize + 1

    # -- exec fold fxns --
    scatter_nl = dnls.scatter.ScatterNl(ps,pt,dilation=dil,exact=True)
    fold_nl = dnls.ifold.iFold(vshape,coords,stride=stride,dilation=dil)
    patches_nl = []
    print_gpu_stats(gpu_stats,"pre-loop")

    for index in range(nbatches):

        # -- batch info --
        qindex = min(qSize * index,npix)
        qSize =  min(qSize, qTotal - qindex)

        # -- get patches --
        queryInds = dnls.utils.inds.get_iquery_batch(qindex,qSize,stride,
                                                     coords,t,device)
        nlDists,nlInds = dnls.simple.search.run(vid,queryInds,flow,k,
                                                ps,pt,ws,wt,chnls,
                                                stride=stride,dilation=dil)
        patches_nl_i = scatter_nl(vid,nlInds)
        del queryInds,nlDists,nlInds
        th.cuda.empty_cache()

        patches_nl_i = patches_nl_i.requires_grad_(True)

        # -- run forward --
        vid_nl = fold_nl(patches_nl_i,qindex)
        patches_nl.append(patches_nl_i)

    # -- vis --
    print_gpu_stats(gpu_stats,"post-loop")

    # -- forward all at once --
    index,qSize = 0,qTotal
    queryInds = dnls.utils.inds.get_iquery_batch(index,qSize,stride,
                                                 coords,t,device)
    nlDists,nlInds = dnls.simple.search.run(vid,queryInds,flow,k,
                                            ps,pt,ws,wt,chnls,
                                            stride=stride,dilation=dil)
    patches_nn = scatter_nl(vid,nlInds)
    patches_nn.requires_grad_(True)
    print_gpu_stats(gpu_stats,"post-search")
    vid_nn,_ = run_fold(patches_nn,t,sq_h,sq_w,stride,dil)
    print_gpu_stats(gpu_stats,"post-fold")

    # -- run backward --
    top,left,btm,right = coords
    vid_grad = th.randn_like(vid_nn)
    vid_nl = fold_nl.vid[:,:,top:btm,left:right]
    th.autograd.backward(vid_nn,vid_grad)
    th.autograd.backward(vid_nl,vid_grad)
    print_gpu_stats(gpu_stats,"post-bkw")

    # -- get grads --
    grad_nn = patches_nn.grad
    grad_nl = th.cat([p_nl.grad for p_nl in patches_nl])

    # -- check forward --
    top,left,btm,right = coords
    error = th.sum((vid_nn - vid_nl)**2).item()
    assert error < 1e-10

    # -- reshape --
    shape_str = '(t h w) 1 1 c ph pw -> t c h w ph pw'
    grad_nn = rearrange(grad_nn,shape_str,t=t,h=nh)
    grad_nl = rearrange(grad_nl,shape_str,t=t,h=nh)

    # -- check backward --
    error = th.sum((grad_nn - grad_nl)**2).item()
    assert error < 1e-10

    # -- clean-up --
    th.cuda.empty_cache()
    del vid,flow
    del vid_nn,vid_nl
    del patches_nl,patches_nn
    del grad_nn,grad_nl,vid_grad
    del queryInds,nlDists,nlInds
    th.cuda.empty_cache()


# @pytest.mark.skip(reason="too long right now")
def test_shifted(ps,stride,dilation,top,btm,left,right):

    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    ws,wt = 10,0
    shift = 2

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device).contiguous()
    flow = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- image params --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    nframes,height,width = t,h,w
    vshape = vid.shape

    # -- sub square --
    coords = [top,left,btm,right]
    sq_h = coords[2] - coords[0]
    sq_w = coords[3] - coords[1]

    # -- shifted sub square --
    shift_coords = [x+shift for x in coords]
    # shift_vshape = (nframes,color,height+shift,width+shift)
    shift_vshape = (nframes,color,height+2*shift,width+2*shift)

    # -- batching info --
    npix = t * h * w
    nh = (sq_h-1)//stride+1
    nw = (sq_w-1)//stride+1
    qTotal = t * nh * nw
    qSize = qTotal
    nbatches = (qTotal-1) // qSize + 1

    # -- exec fold fxns --
    scatter_nl = dnls.scatter.ScatterNl(ps,pt,dilation=dil,exact=True)
    fold_nl = dnls.ifold.iFold(vshape,coords,stride=stride,dilation=dil)
    shift_fold_nl = dnls.ifold.iFold(shift_vshape,shift_coords,
                                     stride=stride,dilation=dil)

    # -- patches for ifold --
    index = 0
    queryInds = dnls.utils.inds.get_iquery_batch(index,qSize,stride,
                                                 coords,t,device)
    nlDists,nlInds = dnls.simple.search.run(vid,queryInds,flow,k,
                                            ps,pt,ws,wt,chnls,
                                            stride=stride,dilation=dil)
    assert th.sum(queryInds - nlInds[:,0]) < 1e-10
    patches_nl = scatter_nl(vid,nlInds)
    patches_nn = patches_nl.clone()
    patches_nn = patches_nn.requires_grad_(True)
    patches_nl = patches_nl.requires_grad_(True)

    #
    # -- test logic --
    #

    # -- run forward --
    top,left,btm,right = coords
    vid_shift = shift_fold_nl(patches_nn,0)
    dnls.testing.data.save_burst(vid_shift,"./output/tests/","vid_shift")
    vid_shift = vid_shift[:,:,top+shift:btm+shift]
    vid_shift = vid_shift[:,:,:,left+shift:right+shift]
    vid_nl = fold_nl(patches_nl,0)
    dnls.testing.data.save_burst(vid_nl,"./output/tests/","vid_nl")
    vid_nl = vid_nl[:,:,top:btm,left:right]

    # -- run backward --
    vid_grad = th.randn_like(vid_nl)
    th.autograd.backward(vid_shift,vid_grad)
    th.autograd.backward(vid_nl,vid_grad)

    # -- check forward --
    delta = vid_shift - vid_nl
    error = th.sum(delta**2).item()
    assert error < 1e-10

    # -- check backward --
    grad_nn = patches_nn.grad
    grad_nl = patches_nl.grad

    # -- rearrange --
    shape_str = '(t h w) 1 1 c ph pw -> t c h w ph pw'
    grad_nn = rearrange(grad_nn,shape_str,t=t,h=nh)
    grad_nl = rearrange(grad_nl,shape_str,t=t,h=nh)

    # -- check backward --
    error = th.sum((grad_nn - grad_nl)**2).item()
    assert error < 1e-10

    # -- clean-up --
    th.cuda.empty_cache()
    del vid,flow
    del vid_shift,vid_nl
    del patches_nl,patches_nn
    del grad_nn,grad_nl,vid_grad
    del queryInds,nlDists,nlInds
    th.cuda.empty_cache()

def test_shrink_search():

    # -- get args --
    ps,stride,dilation = 5,2,1
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    ws,wt = 10,0

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    exact = True
    gpu_stats = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device).contiguous()
    flow = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)
    print_gpu_stats(gpu_stats,"post-io")

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape

    # -- sub square --
    top,left,btm,right = 0,0,h,w
    coords = [top,left,btm,right]
    sq_h = coords[2] - coords[0]
    sq_w = coords[3] - coords[1]

    # -- batching info --
    npix = t * h * w
    n_h = (sq_h-1)//stride+1
    n_w = (sq_w-1)//stride+1
    qTotal = t * n_h * n_w
    qSize = qTotal
    nbatches = (qTotal-1) // qSize + 1

    # -- padded video --
    # padf = 14 # something big
    # vid_pad = pad(vid,[padf,]*4,mode="reflect")

    # -- get folds --
    scatter_nl = dnls.scatter.ScatterNl(ps,pt,dilation=dil,exact=True)
    fold_nl = dnls.ifold.iFold(vshape,coords,stride=stride,dilation=dil)
    wfold_nl = dnls.ifold.iFold(vshape,coords,stride=stride,dilation=dil)

    # -- get patches with dilation --
    qindex,k,pt,chnls = 0,1,1,1
    queryInds = dnls.utils.inds.get_iquery_batch(qindex,qSize,stride,
                                                 coords,t,device)
    nlDists,nlInds = dnls.simple.search.run(vid,queryInds,flow,
                                            k,ps,pt,ws,wt,chnls,
                                            stride=stride,dilation=dil)
    patches = scatter_nl(vid,nlInds[:,[0]])
    ones = th.ones_like(patches)
    vid_f = fold_nl(patches,0)
    wvid_f = wfold_nl(ones,0)
    vid_f /= wvid_f

    # -- inspect --
    # dnls.testing.data.save_burst(vid_f,"./output/tests/","vid_f")
    # diff = th.abs(vid-vid_f)
    # if diff.max() > 1e-3: diff /= diff.max()
    # dnls.testing.data.save_burst(diff,"./output/tests/","diff_f")

    # -- misc --
    error = th.sum((vid_f - vid)**2).item()
    assert error < 1e-10

def run_fold(_patches,_t,_h,_w,_stride=1,_dil=1):
    # -- avoid pytest fixtures --
    patches = _patches
    t,h,w = _t,_h,_w
    stride,dil = _stride,_dil

    # -- unpack --
    ps = patches.shape[-1]
    padf = dil * (ps//2)
    hp,wp = h+2*padf,w+2*padf
    shape_str = '(t np) 1 1 c h w -> t (c h w) np'
    patches = rearrange(patches,shape_str,t=t)
    ones = th.ones_like(patches)

    # -- folded --
    vid_pad = fold(patches,(hp,wp),(ps,ps),stride=stride,dilation=dil)
    vid = center_crop(vid_pad,(h,w))

    # -- weigthed vid --
    wvid_pad = fold(ones,(hp,wp),(ps,ps),stride=stride,dilation=dil)
    wvid = center_crop(wvid_pad,(h,w))

    return vid,wvid

def run_unfold(_vid,_ps,_stride=1,_dil=1):

    # -- avoid fixutres --
    vid,stride = _vid,_stride
    ps,dil = _ps,_dil

    # -- run --
    psHalf = ps//2
    padf = dil * psHalf
    shape_str = 't (c h w) np -> (t np) 1 1 c h w'
    vid_pad = pad(vid,4*[padf,],mode="reflect")
    patches = unfold(vid_pad,(ps,ps),stride=stride,dilation=dil)
    patches = rearrange(patches,shape_str,h=ps,w=ps)
    return patches


