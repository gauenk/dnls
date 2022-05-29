
# -- python --
import torch as th

# -- cpp cuda kernel --
import dnls_cuda


def allocate_patches(nlInds,ps,pt,c):
    device = nlInds.device
    nq,k = nlInds.shape[:2]
    patches = th.zeros((nq,k,pt,c,ps,ps),device=device,dtype=th.float32)
    return patches

class GatherNlFunction(th.autograd.Function):
    """
    [patches -> video] @ nlInds

    nlInds.shape = [NumQueries,K,3]
    patches.shape = [NumQueries,K,pt,c,ps,ps]
    """

    @staticmethod
    def forward(ctx, patches, nlDists, nlInds, vid, wvid, dilation, lam, exact):
        dnls_cuda.gather_forward(vid, wvid, patches, nlDists, nlInds,
                                 dilation, lam, exact)
        ctx.save_for_backward(nlInds)
        ctx.dilation = dilation
        ctx.pt = patches.shape[2]
        ctx.ps = patches.shape[5]
        return vid,wvid

    @staticmethod
    def backward(ctx, grad_vid, grad_wvid):
        nlInds = ctx.saved_tensors[0]
        grad_vid = grad_vid.contiguous()
        dilation = ctx.dilation
        ps,pt = ctx.ps,ctx.pt
        patches = allocate_patches(nlInds,ps,pt,grad_vid.shape[1])
        ones = th.ones_like(nlInds[:,:,0]).type(th.float32)
        dnls_cuda.gather_backward(grad_vid,patches,ones,nlInds,dilation)
        return patches,None,None,None,None,None,None,None

class GatherNl(th.nn.Module):
    # [patches -> video] @ nlInds

    def __init__(self, vid_shape, dilation=1, lam=1., exact=False, device="cuda:0"):
        super(GatherNl, self).__init__()
        self.vid,self.wvid = self.allocate_vid(vid_shape,device)
        self.dilation = dilation
        self.lam = lam
        self.exact = exact

    def allocate_vid(self,vid_shape,device):
        vid = th.zeros(vid_shape,device=device,dtype=th.float32)
        wvid = th.zeros(vid_shape,device=device,dtype=th.float32)
        return vid,wvid

    def forward(self, patches, nlDists, nlInds):
        return GatherNlFunction.apply(patches,nlDists,nlInds,
                                      self.vid,self.wvid,
                                      self.dilation,self.lam,self.exact)

