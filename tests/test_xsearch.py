
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
import dnls.utils.gpu_mem as gpu_mem
from dnls.utils.pads import comp_pads

# -- meshgrid --
import cache_io

# -- test func --
from torch.nn.functional import fold,unfold,pad
from torchvision.transforms.functional import center_crop

# -- paths --
SAVE_DIR = Path("./output/tests/xsearch")

def pytest_generate_tests(metafunc):
    seed = 123
    th.manual_seed(seed)
    np.random.seed(seed)
    # test_lists = {"ps":[3],"stride":[1],"dilation":[1,2],
    #               "top":[3],"btm":[62],"left":[2],"right":[62]}
    # test_lists = {"ps":[4],"stride":[1,2],"dilation":[2],
    #               "top":[4],"btm":[64],"left":[1],"right":[61]}
    # test_lists = {"ps":[3,4,5,6,7,8],"stride":[1,2,3,4,5],"dilation":[1,2,3,4,5],
    #               "top":[3],"btm":[57],"left":[7],"right":[57]}
    # test_lists = {"ps":[3],"stride":[2],"dilation":[2],
    #               "top":[3],"btm":[57],"left":[7],"right":[57]}
    test_lists = {"ps":[7],"stride":[4],"dilation":[1],"wt":[0],
                  "ws":[-1],"top":[0],"btm":[64],"left":[0],"right":[64],"k":[-1,5]}
    # test_lists = {"ps":[3,4,5,6,7,8],"stride":[1,2,3,4,5,8],"dilation":[1,2,3,4,5,8],
    #               "top":[1,11],"btm":[50,57],"left":[3,7],"right":[57,30]}
    for key,val in test_lists.items():
        if key in metafunc.fixturenames:
            metafunc.parametrize(key,val)

#
#
# -- Primary Testing Class --
#
#

# @pytest.mark.skip(reason="too long right now")
def test_nn_v1(ps,stride,dilation,top,btm,left,right):


    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    ws,wt = 10,0
    ws = -1
    k = -1

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    gpu_stats = False
    adj = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device)[:1,].contiguous()
    gpu_mem.print_gpu_stats(gpu_stats,"post-io")

    # -- grow img --
    vid = th.cat([vid,vid],-1)
    # vid = th.cat([vid,vid],-1)
    # vid = th.cat([vid,vid],-2)
    vid = th.cat([vid,vid],-2)

    # -- compute flow --
    flows = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape

    # -- run search --
    nlDists_nn,_ = dnls.simple.xsearch_nn.run_nn(vid,ps,stride=stride,dilation=dil)
    nlDists_simp,nlInds_simp = dnls.simple.xsearch_nn.run(vid,ps,stride=stride,dilation=dil)

    # -- viz --
    # print("nlDists_nn.shape: ",nlDists_nn.shape)
    # print(nlDists_nn[:3,:3,:3,:3])
    # print(nlDists_simp[:3,:3,:3,:3])

    # -- compare --
    tol = 1e-10
    error = th.sum(th.abs(nlDists_simp - nlDists_nn)).item()
    if error > tol: print("error: ",error)
    assert error < tol

def test_nn_v2(ps,stride,dilation):


    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    k,pt = 1,1
    wt = 0
    ws = -1
    k = -1
    stride0 = stride
    stride1 = 1

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    gpu_stats = False
    adj = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device)[:1,].contiguous()
    gpu_mem.print_gpu_stats(gpu_stats,"post-io")

    # -- grow img --
    vid = th.cat([vid,vid],-1)
    # vid = th.cat([vid,vid],-1)
    # vid = th.cat([vid,vid],-2)
    vid = th.cat([vid,vid],-2)

    # -- normalize --
    vid /= vid.max()

    # -- compute flow --
    flows = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape
    chnls = vid.shape[1]

    # -- sub square --
    top,btm,left,right = 0,h,0,w
    coords = [top,left,btm,right]
    # sq_h = coords[2] - coords[0]
    # sq_w = coords[3] - coords[1]

    # -- pads --
    oh0,ow0,hp,wp = comp_pads(vid.shape, ps, stride0, dil)
    oh1,ow1,_,_ = comp_pads(vid.shape, ps, stride1, dil)
    n_h = (hp - (ps-1)*dil - 1)//stride0 + 1
    n_w = (wp - (ps-1)*dil - 1)//stride0 + 1

    # -- batching info --
    npix = t * h * w
    ntotal = t * n_h * n_w
    nbatch = ntotal
    nbatches = (ntotal-1) // nbatch + 1

    # -- exec fold fxns --
    xsearch = dnls.xsearch.CrossSearchNl(flows.fflow, flows.bflow,
                                         k, ps, pt, ws, wt, oh0, ow0, oh1, ow1,
                                         chnls=chnls,dilation=dil, stride=stride1,
                                         reflect_bounds=True,use_k=False,use_search_abs=True)
    # -- query inds --
    qindex = 0
    iqueries = dnls.utils.inds.get_iquery_batch(qindex,nbatch,stride0,
                                                coords,t,device)

    # -- run search --
    # vidr = None
    # vidr = 10*th.ones_like(vid)
    # vidr = vid
    vidr = th.rand_like(vid)
    # vidr[th.where(th.abs(vidr) > 0.2)] = 1
    # vidr[th.where(th.abs(vidr) < 1)] = 0
    # print(th.unique(vidr))
    # vid = th.ones_like(vid)
    # vid = th.rand_like(vid)
    # vid[th.where(th.abs(vid) > 0.2)] = 1
    # vid[th.where(th.abs(vid) < 1)] = 0

    # ones = th.ones_like(vid)
    nlDists_cu,nlInds_cu = xsearch(vid,iqueries,vid1=vidr)

    # -- flip cu --
    # print(nlDists_cu.shape)
    nlDists_cu = rearrange(nlDists_cu,'(sh sw) (h w) -> h w sh sw',sh=n_h,h=h)

    # -- run search --
    nlDists_nn,_ = dnls.simple.xsearch_nn.run_nn(vid,ps,stride=stride0,
                                                 dilation=dil,vid1=vidr)
    # print(nlDists_nn.shape)
    # print(nlDists_cu.shape)

    # -- viz --
    # print(nlDists_cu[:2,:2,:2,:2])
    # print(nlDists_nn[:2,:2,:2,:2])

    # diff = th.abs(nlDists_cu - nlDists_nn).mean((-1,-2))
    # if diff.max() > 1e-5: diff /= diff.max()
    # diff = repeat(diff,'h w -> 1 c h w',c=3)
    # dnls.testing.data.save_burst(diff,SAVE_DIR,"nn2_diff")

    # diff = th.abs(nlDists_cu - nlDists_nn).mean((0,1))
    # if diff.max() > 1e-5: diff /= diff.max()
    # diff = repeat(diff,'h w -> 1 c h w',c=3)
    # dnls.testing.data.save_burst(diff,SAVE_DIR,"nn2_diff_t")

    # -- compare --
    tol = 1e-5
    error = th.mean(th.abs(nlDists_cu - nlDists_nn)).item()
    if error > tol: print("error: ",error)
    assert error < tol

    tol = 1e-4
    max_error = th.abs(nlDists_cu - nlDists_nn).max().item()
    if max_error > tol: print("max error: ",max_error)
    assert max_error < tol


def test_nn_bwd(ps,stride,dilation):


    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    wt = 0
    ws = -1
    k = -1
    stride0 = stride
    stride1 = 1

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    gpu_stats = False
    adj = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device)[:1,].contiguous()/255.
    gpu_mem.print_gpu_stats(gpu_stats,"post-io")

    # -- grow img --
    # vid = th.cat([vid,vid],-1)
    # vid = th.cat([vid,vid],-1)
    # vid = th.cat([vid,vid],-2)
    # vid = th.cat([vid,vid],-2)
    # print("vid.shape: ",vid.shape)

    # -- compute flow --
    flows = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape
    chnls = vid.shape[1]

    # -- sub square --
    top,btm,left,right = 0,h,0,w
    coords = [top,left,btm,right]
    # sq_h = coords[2] - coords[0]
    # sq_w = coords[3] - coords[1]

    # -- pads --
    oh0,ow0,hp,wp = comp_pads(vid.shape, ps, stride0, dil)
    oh1,ow1,_,_ = comp_pads(vid.shape, ps, stride1, dil)
    n_h = (hp - (ps-1)*dil - 1)//stride0 + 1
    n_w = (wp - (ps-1)*dil - 1)//stride0 + 1

    # -- batching info --
    npix = t * h * w
    ntotal = t * n_h * n_w
    nbatch = ntotal
    nbatches = (ntotal-1) // nbatch + 1

    # -- swap --
    oh0,ow0,_,_ = comp_pads(vid.shape, ps, stride0, dil)
    oh1,ow1,_,_ = comp_pads(vid.shape, ps, stride1, dil)

    # -- exec fold fxns --
    xsearch = dnls.xsearch.CrossSearchNl(flows.fflow, flows.bflow, k, ps, pt,
                                         ws, wt, oh0, ow0, oh1, ow1,
                                         chnls=chnls,dilation=dil, stride=stride1,
                                         reflect_bounds=True,use_k=False,exact=True,use_search_abs=True)
    # -- query inds
    qindex = 0
    iqueries = dnls.utils.inds.get_iquery_batch(qindex,nbatch,stride0,
                                                coords,t,device)
    # -- binary image to remove float error --
    # vidr = None
    # vidr = 10*th.ones_like(vid)
    # vid = th.round(th.rand_like(vid),decimals=2)*100
    # vid = th.rand_like(vid)*1.5
    # vid = th.round(th.rand_like(vid),decimals=10)
    # vidr = th.round(th.rand_like(vid),decimals=3)
    # vidr = th.round(th.rand_like(vid),decimals=3)
    # vid = th.round(th.rand_like(vid),decimals=2)*100.
    # vidr = th.round(th.rand_like(vid),decimals=2)*100.
    # vid = vid.type(th.float32)
    # vidr = vidr.type(th.float32)
    # vidr[th.where(th.abs(vidr) > 0.2)] = 1
    # vidr[th.where(th.abs(vidr) < 1)] = 0
    # # vid = th.ones_like(vid)
    # vid = th.rand_like(vid)
    # vid[th.where(th.abs(vid) > 0.2)] = 1
    # vid[th.where(th.abs(vid) < 1)] = 0

    # vid = vidr.clone()
    # vid[:,:,:3,:3] = 0
    # vid[:,:,0,0] = 0
    # vidr[:,:,:3,:3] = 0


    # -- allow grads --
    vid_cu = vid.clone()
    vid_nn = vid.clone()
    vid_cu.requires_grad_(True)
    vid_nn.requires_grad_(True)

    vidr_cu = vid_cu
    vidr_nn = vid_nn

    # vidr_cu = vidr.clone()
    # vidr_cu.requires_grad_(True)
    # vidr_nn = vidr.clone()
    # vidr_nn.requires_grad_(True)



    #
    # -- run search --
    #

    # -- run cu --
    nlDists_cu,nlInds_cu = xsearch(vid_cu,iqueries,vid1=vidr_cu)
    nlDists_cu = rearrange(nlDists_cu,'(sh sw) (h w) -> h w sh sw',sh=n_h,h=h)
    # nlDists_cu = rearrange(nlDists_cu,'(sh sw) h w -> h w sh sw',sh=n_h)

    # -- run nn --
    nlDists_nn,_ = dnls.simple.xsearch_nn.run_nn(vid_nn,ps,stride=stride0,
                                                 dilation=dil,vid1=vidr_nn)
    sh = nlDists_nn.shape[-1]

    # -- vis --
    diff = th.abs(nlDists_cu - nlDists_nn)
    args = th.where(diff>1e-10)
    # for i in range(len(args)):
    #     print(i,th.unique(args[i]))
    # if diff.max() > 1e-10: diff /= diff.max()
    # dnls.testing.data.save_burst(diff[0,0][None,None],"./output/tests/xsearch/","diff")
    # dnls.testing.data.save_burst(diff[:,:,0,0][None,None],"./output/tests/xsearch/","diff_d00")

    # -- compare fwd --
    max_error = th.abs(nlDists_cu - nlDists_nn).max().item()
    # print("max error: ",max_error)
    assert max_error < 1e-3

    error = th.mean(th.abs(nlDists_cu - nlDists_nn)).item()
    # print("error: ",error)
    assert error < 1e-4

    # -- compute grad --
    nlDists_grad = th.ones_like(nlDists_nn)
    th.autograd.backward(nlDists_nn,nlDists_grad)
    th.autograd.backward(nlDists_cu,nlDists_grad)

    # -- get grads --
    grads_cu = vidr_cu.grad
    grads_nn = vidr_nn.grad
    # print("cu,nn")
    # print("-"*10)
    # print(grads_cu[0,0,:3,:3])
    # print(grads_nn[0,0,:3,:3])
    # print("-"*10)
    # print(grads_cu[0,0,16:19,16:19])
    # print(grads_nn[0,0,16:19,16:19])
    # print("-"*10)
    # print(grads_cu[0,0,30:33,30:33])
    # print(grads_nn[0,0,30:33,30:33])
    # print("-"*10)
    print(grads_cu[0,0,-3:,-3:])
    print(grads_nn[0,0,-3:,-3:])
    # print("-"*10)

    # -- viz [the error map looks weird] --
    # print(grads_cu[0,-1,-10:,-10:])
    # print(grads_nn[0,-1,-10:,-10:])
    diff = (grads_cu -grads_nn).abs()/(grads_nn.abs()+1e-8)
    print(diff.max())
    print(diff.mean((0,2,3)))
    diff /= diff.max()
    dnls.testing.data.save_burst(diff[:,[0]],SAVE_DIR,"grad_diff_0")
    dnls.testing.data.save_burst(diff[:,[1]],SAVE_DIR,"grad_diff_1")
    dnls.testing.data.save_burst(diff[:,[2]],SAVE_DIR,"grad_diff_2")

    # -- compare grads --
    rel_error = th.abs(grads_nn - grads_cu)/(th.abs(grads_nn)+1e-8)
    args = th.where(th.abs(grads_nn) > 1e-3)
    rel_error_nz = rel_error[args]
    args_z = th.where(th.abs(grads_nn) <= 1e-3)
    # print(args_z)

    # args = th.where(rel_error> 0.5)
    # print(th.sum(th.abs(grads_cu[args])))
    # print(th.sum(th.abs(grads_nn[args])))
    # print(grads_cu[args],grads_nn[args])
    # print(len(args[0]))
    # print(args)

    tol = 1e-3
    error = th.max(rel_error_nz).item()
    if error > tol: print("Max Error: ",error)
    print("Max Error: ",error)
    assert error < tol

    tol = 1e-4
    error = th.mean(rel_error_nz).item()
    if error > tol: print("Mean Error: ",error)
    print("Mean Error: ",error)
    assert error < tol

    # error = th.max(th.abs(grads_cu[args_z])).item()
    # print("Max Error: ",error)
    # assert error < 1e-4

    # error = th.mean(th.abs(grads_cu[args_z])).item()
    # print("Mean Error: ",error)
    # assert error < 1e-4


# @pytest.mark.skip(reason="too long right now")
def test_simp(ps,stride,dilation,top,btm,left,right):


    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 3,1,1
    ws,wt = 10,0
    ws = -1
    k = -1

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    gpu_stats = False
    adj = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device)[:1,].contiguous()/255.
    gpu_mem.print_gpu_stats(gpu_stats,"post-io")
    vid[...] = th.randn_like(vid)

    # -- compute flow --
    flows = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape

    # -- sub square --
    top,left,btm,right=0,0,h,w
    coords = [top,left,btm,right]
    sq_h = coords[2] - coords[0]
    sq_w = coords[3] - coords[1]

    # -- batching info --
    stride0 = stride
    stride1 = 1
    npix = t * h * w
    nh = (sq_h-1)//stride0+1
    nw = (sq_w-1)//stride0+1
    ntotal = t * nh * nw
    nbatch = ntotal
    nbatches = (ntotal-1) // nbatch + 1

    # -- query inds --
    qindex = 0
    iqueries = dnls.utils.inds.get_iquery_batch(qindex,nbatch,stride0,
                                                coords,t,device)

    # -- pads --
    oh0,ow0,hp,wp = comp_pads(vid.shape, ps, stride0, dil)
    oh1,ow1,_,_ = comp_pads(vid.shape, ps, stride1, dil)
    # n_h = (sq_h-1)//stride0+1 # corrected
    # n_w = (sq_w-1)//stride0+1

    # -- run search --
    nlDists_simp,_ = dnls.simple.xsearch_nn.run(vid,ps,stride=stride0,dilation=dil)
    # print("iqueries.shape: ",iqueries.shape)
    nlDists_cu,nlInds_cu = dnls.simple.xsearch.run(vid,iqueries,flows,k,
                                                   ps,pt,ws,wt,chnls,
                                                   stride0=stride0,stride1=stride1,
                                                   dilation=dil,
                                                   use_search_abs=True,use_k=False)
    # print(nlDists_simp.shape)
    # print(nlDists_cu.shape)
    nlDists_cu = rearrange(nlDists_cu,'(nh nw) (h w) -> h w nh nw',h=h,nh=nh)
    # nlDists_cu = rearrange(nlDists_cu,'(h w) (nh nw) -> h w nh nw',h=h,nh=nh)
    # print(nlDists_cu.shape)

    # -- viz --
    # print(nlDists_simp[8,8,:3,:3])
    # print(nlDists_cu[8,8,:3,:3])

    # -- compare --
    error = th.sum(th.abs(nlDists_cu - nlDists_simp)).item()
    assert error < 1e-10

    # perc_neq = th.mean((nlInds_cu != nlInds_simp)*1.)
    # print("perc_neq: ",perc_neq)
    # assert perc_neq < 0.05

def test_cu(ps,stride,dilation,top,btm,left,right,k):


    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,pt = 3,1
    wt = 2
    ws = -1 if k == -1 else 10
    use_search_abs = k == -1
    use_k = not(k == -1)
    # print(ws,k,use_search_abs,use_k)

    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    gpu_stats = False
    adj = 0

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device)[:2,].contiguous()/255.
    gpu_mem.print_gpu_stats(gpu_stats,"post-io")

    # -- compute flow --
    flows = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)

    # -- unpack image --
    device = vid.device
    shape = vid.shape
    t,color,h,w = shape
    vshape = vid.shape

    # -- sub square --
    top,left,btm,right=0,0,h,w
    coords = [top,left,btm,right]
    sq_h = coords[2] - coords[0]
    sq_w = coords[3] - coords[1]

    # -- batching info --
    stride0 = stride
    stride1 = 1
    npix = t * h * w
    nh = (sq_h-1)//stride0+1
    nw = (sq_w-1)//stride0+1
    ntotal = t * nh * nw
    nbatch = ntotal
    nbatches = (ntotal-1) // nbatch + 1

    # -- pads --
    oh0,ow0,_,_ = comp_pads(vid.shape, ps, stride0, dil)
    oh1,ow1,hp,wp = comp_pads(vid.shape, ps, stride1, dil)

    # -- exec fold fxns --
    xsearch_nl = dnls.xsearch.CrossSearchNl(flows.fflow, flows.bflow, k, ps, pt,
                                            ws, wt, oh0, ow0, oh1, ow1,
                                            chnls=chnls,dilation=dil, stride=stride1,
                                            use_k=use_k,use_search_abs=use_search_abs)
    scatter_nl = dnls.scatter.ScatterNl(ps,pt,dilation=dil,exact=True)
    fold_nl = dnls.ifold.iFold(vshape,coords,stride=stride1,dilation=dil,adj=adj)
    patches_nl = []
    gpu_mem.print_gpu_stats(gpu_stats,"start-exec")

    # -- query inds
    qindex = 0
    iqueries = dnls.utils.inds.get_iquery_batch(qindex,nbatch,stride0,
                                                coords,t,device)

    # -- run search --
    nlDists_cu,nlInds_cu = xsearch_nl(vid,iqueries)
    nlDists_simp,nlInds_simp = dnls.simple.xsearch.run(vid,iqueries,flows,k,
                                                       ps,pt,ws,wt,chnls,
                                                       stride0=stride0,stride1=stride1,dilation=dil,
                                                       use_k=use_k,use_search_abs=use_search_abs)
    # print("nlDists_cu.shape: ",nlDists_cu.shape)
    # print("nlDists_simp.shape: ",nlDists_simp.shape)
    # print(nlDists_cu[:3,:2])
    # print(nlDists_simp[:3,:2])

    # -- reshape --
    nq = iqueries.shape[0]
    nlDists_cu = nlDists_cu.view(nq,-1)
    nlDists_simp = nlDists_simp.view(nq,-1)

    # -- compare --
    error = th.mean(th.abs(nlDists_cu - nlDists_simp)).item()
    assert error < 1e-6

@pytest.mark.skip(reason="too long right now")
def test_batched(ps,stride,dilation,top,btm,left,right,ws,wt):

    # -- get args --
    dil = dilation
    dname,ext = "davis_baseball_64x64","jpg"
    chnls,k,pt = 1,1,1
    ws,wt = 10,0
    ws = -1
    k = -1


    # -- init vars --
    device = "cuda:0"
    clean_flow = True
    comp_flow = False
    exact = True
    exact = True
    gpu_stats = False
    adj = False

    # -- load data --
    vid = dnls.testing.data.load_burst("./data/",dname,ext=ext)
    vid = th.from_numpy(vid).to(device).contiguous()
    flows = dnls.testing.flow.get_flow(comp_flow,clean_flow,vid,vid,0.)
    gpu_mem.print_gpu_stats(gpu_stats,"post-io")

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
    ntotal = t * nh * nw
    nbatch = 512
    nbatches = (ntotal-1) // nbatch + 1

    # -- exec fold fxns --
    search_nl = dnls.xsearch.CrossSearchNl(flows.fflow, flows.bflow, k, ps, pt,
                                           ws, wt, chnls=chnls,dilation=dil, stride=stride)
    scatter_nl = dnls.scatter.ScatterNl(ps,pt,dilation=dil,exact=True)
    fold_nl = dnls.ifold.iFold(vshape,coords,stride=stride,dilation=dil,adj=adj)
    patches_nl = []
    gpu_mem.print_gpu_stats(gpu_stats,"pre-loop")

    for index in range(nbatches):

        # -- batch info --
        qindex = min(nbatch * index,npix)
        nbatch =  min(nbatch, ntotal - qindex)

        # -- get patches --
        iqueries = dnls.utils.inds.get_iquery_batch(qindex,nbatch,stride,
                                                     coords,t,device)
        nlDists_simp,nlInds_simp = dnls.simple.xsearch.run(vid,iqueries,flows,k,
                                                           ps,pt,ws,wt,chnls,
                                                           stride0=stride0,stride1=stride1,dilation=dil,
                                                           use_k=use_k,use_search_abs=use_search_abs)
        nlDists_cu,nlInds_cu = search_nl(vid,iqueries,flows,k,
                                         ps,pt,ws,wt,chnls,
                                         stride=stride,dilation=dil)
        patches_nl_i = scatter_nl(vid,nlInds_simp)
        del iqueries,nlDists,nlInds
        th.cuda.empty_cache()

        patches_nl_i = patches_nl_i.requires_grad_(True)

        # -- run forward --
        vid_nl = fold_nl(patches_nl_i,qindex)
        patches_nl.append(patches_nl_i)

    # -- vis --
    gpu_mem.print_gpu_stats(gpu_stats,"post-loop")

    # -- forward all at once --
    index,nbatch = 0,ntotal
    iqueries = dnls.utils.inds.get_iquery_batch(index,nbatch,stride,
                                                 coords,t,device)
    nlDists,nlInds = dnls.simple.xsearch.run(vid,iqueries,flow,k,
                                             ps,pt,ws,wt,chnls,
                                             stride=stride,dilation=dil)
    patches_nn = scatter_nl(vid,nlInds)
    patches_nn.requires_grad_(True)
    gpu_mem.print_gpu_stats(gpu_stats,"post-search")
    vid_nn,_ = run_fold(patches_nn,t,sq_h,sq_w,stride,dil,adj)
    gpu_mem.print_gpu_stats(gpu_stats,"post-fold")

    # -- run backward --
    top,left,btm,right = coords
    vid_grad = th.randn_like(vid_nn)
    vid_nl = fold_nl.vid[:,:,top:btm,left:right]
    th.autograd.backward(vid_nn,vid_grad)
    th.autograd.backward(vid_nl,vid_grad)
    gpu_mem.print_gpu_stats(gpu_stats,"post-bkw")
    # dnls.testing.data.save_burst(vid_nn,"./output/","vid_nn")
    # dnls.testing.data.save_burst(vid_nl,"./output/","vid_nl")

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
    del iqueries,nlDists,nlInds
    th.cuda.empty_cache()
    th.cuda.synchronize()

