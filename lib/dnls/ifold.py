"""

Fold but with an inset rectangle of any size

"""


# -- python --
import torch as th

# -- cpp cuda kernel --
import dnls_cuda


def allocate_patches(nq,k,ps,pt,c,device):
    patches = th.zeros((nq,k,pt,c,ps,ps),device=device,dtype=th.float32)
    return patches

class iFoldFunction(th.autograd.Function):
    """
    [patches -> video] @ nlInds

    nlInds.shape = [NumQueries,K,3]
    patches.shape = [NumQueries,K,pt,c,ps,ps]
    """

    @staticmethod
    def forward(ctx, patches, vid, coords, qStart, stride, dilation, adj_h, adj_w):
        top,left,btm,right = coords
        dnls_cuda.ifold_forward(vid, patches,
                                top, left, btm, right,
                                qStart, stride, dilation, adj_h, adj_w)
        ctx.coords = coords
        ctx.qStart = qStart
        ctx.stride = stride
        ctx.qNum = patches.shape[0]
        ctx.dilation = dilation
        ctx.adj_h = adj_h
        ctx.adj_w = adj_w
        ctx.pt = patches.shape[2]
        ctx.ps = patches.shape[5]
        return vid

    @staticmethod
    def backward(ctx, grad_vid):

        # -- unpack --
        grad_vid = grad_vid.contiguous()
        ps,pt = ctx.ps,ctx.pt
        dilation = ctx.dilation
        qStart = ctx.qStart
        stride = ctx.stride
        qNum = ctx.qNum
        adj_h = ctx.adj_h
        adj_w = ctx.adj_w
        top,left,btm,right = ctx.coords

        # -- alloc --
        t,c,h,w  = grad_vid.shape
        npix = t*h*w
        colors = grad_vid.shape[1]
        device = grad_vid.device
        grad_patches = allocate_patches(qNum,1,ps,pt,colors,device)

        # -- backward --
        dnls_cuda.ifold_backward(grad_vid,grad_patches,
                                 top, left, btm, right,
                                 qStart,stride,dilation,
                                 adj_h,adj_w)

        return grad_patches,None,None,None,None,None,None,None

class iFold(th.nn.Module):
    # [patches -> video] @ nlInds [with k == 1]

    def __init__(self, vid_shape, coords, stride=1, dilation=1, adj_h=0, adj_w=0, device="cuda:0"):
        super(iFold, self).__init__()
        self.device = device
        self.vshape = vid_shape
        self.vid_shape = vid_shape
        self.vid = self.allocate_vid(vid_shape,device)
        self.stride = stride
        self.dilation = dilation
        self.adj_h = adj_h
        self.adj_w = adj_w
        self.coords = coords
        if self.coords is None:
            t,c,h,w = vid_shape
            self.coords = [0,0,h,w]

    def allocate_vid(self,vid_shape,device):
        vid = th.zeros(vid_shape,device=device,dtype=th.float32)
        return vid

    def forward(self, patches, qStart):
        bpatches,qStart = patches,qStart
        vid = self.allocate_vid(self.vid_shape,self.device)
        vid = iFoldFunction.apply(bpatches, vid, self.coords, qStart,
                                  self.stride,self.dilation,self.adj_h,self.adj_w)
        self.vid = self.vid + vid
        return self.vid

