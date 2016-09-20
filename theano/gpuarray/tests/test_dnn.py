from __future__ import absolute_import, print_function, division
import logging

from nose.plugins.skip import SkipTest
from nose_parameterized import parameterized
import numpy
from itertools import product, chain

import theano
from six import StringIO
import theano.tensor as T
import theano.tests.unittest_tools as utt
from theano.sandbox.neighbours import images2neibs
from theano.tensor.signal.pool import pool_2d, pool_3d
from theano.tensor.signal.pool import Pool, MaxPoolGrad, AveragePoolGrad

from .. import dnn
from ..basic_ops import GpuAllocEmpty
from ..type import gpuarray_shared_constructor

from .config import mode_with_gpu, mode_without_gpu, test_ctx_name
from . import test_nnet

from theano.configdefaults import SUPPORTED_DNN_CONV_ALGO_FWD


def test_dnn_conv_desc_merge():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    kern_shp = T.as_tensor_variable(
        numpy.asarray([3, 1, 2, 2]).astype('int64'))
    desc1 = dnn.GpuDnnConvDesc(border_mode='valid', subsample=(2, 2),
                               conv_mode='conv')(kern_shp)
    desc2 = dnn.GpuDnnConvDesc(border_mode='full', subsample=(1, 1),
                               conv_mode='cross')(kern_shp)
    # CDataType is not DeepCopyable so this will crash if we don't use
    # borrow=True
    f = theano.function([], [theano.Out(desc1, borrow=True),
                             theano.Out(desc2, borrow=True)])

    d1, d2 = f()

    # This will be the case if they are merged, which would be bad.
    assert d1 != d2


def test_dnn_conv_merge():
    # This test that we merge correctly multiple dnn_conv.
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    img_shp = [2, 5, 6, 8]
    kern_shp = [3, 5, 5, 6]
    img = T.ftensor4('img')
    kern = T.ftensor4('kern')
    out = T.ftensor4('out')
    desc = dnn.GpuDnnConvDesc(
        border_mode='valid')(kern.shape)

    # Test forward op
    o1 = dnn.dnn_conv(img, kern)
    o2 = dnn.dnn_conv(img, kern)
    f = theano.function([img, kern], [o1, o2], mode=mode_with_gpu)
    d1, d2 = f(numpy.random.rand(*img_shp).astype('float32'),
               numpy.random.rand(*kern_shp).astype('float32'))
    topo = f.maker.fgraph.toposort()
    assert len([n for n in topo if isinstance(n.op, dnn.GpuDnnConv)]) == 1

    # Test grad w op
    o1 = dnn.GpuDnnConvGradW()(img, kern, out, desc)
    o2 = dnn.GpuDnnConvGradW()(img, kern, out, desc)
    f = theano.function([img, kern, out], [o1, o2], mode=mode_with_gpu)
    topo = f.maker.fgraph.toposort()
    assert len([n for n in topo if isinstance(n.op, dnn.GpuDnnConvGradW)]) == 1

    # Test grad i op
    o1 = dnn.GpuDnnConvGradI()(img, kern, out, desc)
    o2 = dnn.GpuDnnConvGradI()(img, kern, out, desc)
    f = theano.function([img, kern, out], [o1, o2], mode=mode_with_gpu)
    topo = f.maker.fgraph.toposort()
    assert len([n for n in topo if isinstance(n.op, dnn.GpuDnnConvGradI)]) == 1


def test_dnn_conv_inplace():
    """This test that we have inplace work correctly even when
    GpuAllocEmpty get merged together.

    """
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    img_shp = [2, 5, 6, 8]
    kern_shp = [3, 5, 5, 6]
    img = T.ftensor4('img')
    kern = T.ftensor4('kern')
    out = T.ftensor4('out')
    desc1 = dnn.GpuDnnConvDesc(border_mode='valid', conv_mode='conv')(
        kern.shape)
    desc2 = dnn.GpuDnnConvDesc(
        border_mode='valid', conv_mode='cross')(kern.shape)

    # Test forward op
    o1 = dnn.dnn_conv(img, kern, conv_mode='conv')
    o2 = dnn.dnn_conv(img, kern, conv_mode='cross')
    f = theano.function([img, kern], [o1, o2], mode=mode_with_gpu)
    d1, d2 = f(numpy.random.rand(*img_shp).astype('float32'),
               numpy.random.rand(*kern_shp).astype('float32'))
    topo = f.maker.fgraph.toposort()
    convs = [n for n in topo if isinstance(n.op, dnn.GpuDnnConv)]
    assert len(convs) == 2
    assert all([node.op.inplace for node in convs])
    assert len([n for n in topo if isinstance(n.op, GpuAllocEmpty)]) == 2

    # Test grad w op
    out = GpuAllocEmpty(kern.dtype, test_ctx_name)(*kern.shape)
    o1 = dnn.GpuDnnConvGradW()(img, kern, out, desc1)
    o2 = dnn.GpuDnnConvGradW()(img, kern, out, desc2)
    f = theano.function([img, kern], [o1, o2], mode=mode_with_gpu)
    topo = f.maker.fgraph.toposort()
    convs = [n for n in topo if isinstance(n.op, dnn.GpuDnnConvGradW)]
    assert len(convs) == 2
    assert all([node.op.inplace for node in convs])
    assert len([n for n in topo if isinstance(n.op, GpuAllocEmpty)]) == 2

    # Test grad i op
    out = GpuAllocEmpty(img.dtype, test_ctx_name)(*img.shape)
    o1 = dnn.GpuDnnConvGradI()(img, kern, out, desc1)
    o2 = dnn.GpuDnnConvGradI()(img, kern, out, desc2)
    f = theano.function([img, kern], [o1, o2], mode=mode_with_gpu)
    topo = f.maker.fgraph.toposort()
    convs = [n for n in topo if isinstance(n.op, dnn.GpuDnnConvGradI)]
    assert len(convs) == 2
    assert all([node.op.inplace for node in convs])
    assert len([n for n in topo if isinstance(n.op, GpuAllocEmpty)]) == 2


def pool_2d_i2n(input, ds=(2, 2), strides=None,
                pad=(0, 0),
                pool_function=T.max, mode='ignore_borders'):
    if strides is None:
        strides = ds

    if strides[0] > ds[0] or strides[1] > ds[1]:
        raise RuntimeError(
            "strides should be smaller than or equal to ds,"
            " strides=(%d, %d) and ds=(%d, %d)" %
            (strides + ds))
    shape = input.shape
    if pad != (0, 0):
        assert pool_function is T.max
        pad_x = pad[0]
        pad_y = pad[1]
        a = T.alloc(-numpy.inf, shape[0], shape[1], shape[2] + pad_x * 2,
                    shape[3] + pad_y * 2)
        input = T.set_subtensor(a[:, :,
                                  pad_x:pad_x + shape[2],
                                  pad_y:pad_y + shape[3]],
                                input)
        shape = input.shape

    neibs = images2neibs(input, ds, strides, mode=mode)
    pooled_neibs = pool_function(neibs, axis=1)

    output_width = (shape[2] - ds[0]) // strides[0] + 1
    output_height = (shape[3] - ds[1]) // strides[1] + 1

    pooled_output = pooled_neibs.reshape((shape[0], shape[1],
                                          output_width, output_height))
    return pooled_output


def pool3d2d(input, ds=(2, 2, 2), strides=None, pad=(0, 0, 0),
             pool_function=T.max, mode='ignore_borders'):
    if strides is None:
        strides = ds

    assert input.ndim == 5
    shape = input.shape

    # reshape to B, C*0, 1, 2 and do the pooling on 1, 2
    first = input.reshape((shape[0], shape[1] * shape[2], shape[3], shape[4]))
    pooled1 = pool_2d_i2n(first, ds=ds[1:], strides=strides[1:], pad=pad[1:],
                          pool_function=pool_function, mode=mode)

    shp1 = pooled1.shape
    # reshape to B, C, 0, 1*2 and do the pooling on 0
    second = pooled1.reshape((shape[0], shape[1], shape[2], shp1[2] * shp1[3]))
    pooled2 = pool_2d_i2n(second, ds=(ds[0], 1), strides=(strides[0], 1),
                          pad=(pad[0], 0), pool_function=pool_function, mode=mode)
    shp2 = pooled2.shape
    return pooled2.reshape((shape[0], shape[1], shp2[2], shp1[2], shp1[3]))


def test_pooling():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)

    # 'average_exc_pad' is disabled for versions < 4004
    if dnn.version(raises=False) < 4004:
        modes = ('max', 'average_inc_pad')
    else:
        modes = ('max', 'average_inc_pad', 'average_exc_pad')

    x = T.ftensor4()
    for mode, pad in product(modes,
                             ((0, 0), (1, 0), (0, 1), (2, 3), (3, 2))):
        if mode == 'max':
            func = T.max
        else:
            func = T.mean

        if pad != (0, 0) and func is T.mean:
            continue

        for ws in (4, 2, 5):
            for stride in (2, 3):
                if stride > ws:
                    continue
                if pad[0] > stride or pad[1] > stride:
                    # Not implemented
                    continue
                # We will check that the opt introduced it.
                out1 = pool_2d(x, (ws, ws),
                               st=(stride, stride),
                               ignore_border=True,
                               padding=pad, mode=mode)
                out2 = pool_2d_i2n(x, ds=(ws, ws), strides=(stride, stride),
                                   pad=pad,
                                   pool_function=func)
                mode_without_gpu2 = mode_without_gpu.including()
                mode_without_gpu2.check_isfinite = False
                f1 = theano.function([x], out1, mode=mode_with_gpu)
                assert any([isinstance(node.op, dnn.GpuDnnPool)
                            for node in f1.maker.fgraph.apply_nodes])
                f2 = theano.function([x], out2, mode=mode_without_gpu2)
                assert not any([isinstance(node.op, dnn.GpuDnnPool)
                                for node in f2.maker.fgraph.apply_nodes])
                for shp in [(1, 10, 100, 100),
                            (1, 3, 99, 99),
                            (32, 1, 147, 197),
                            ]:
                    data = numpy.random.normal(0, 1, shp).astype("float32")
                    a = f1(data)
                    b = f2(data)

                    utt.assert_allclose(a, b)

        # Test the grad
        for shp in [(1, 1, 2, 2),
                    (1, 1, 3, 3)]:
            data = numpy.random.normal(0, 1, shp).astype("float32") * 10

            ws = 2
            stride = 2
            if pad[0] > stride or pad[1] > stride:
                # Not implemented
                continue

            # This test the CPU grad + opt + GPU implemtentation
            def fn(x):
                return pool_2d(x, (ws, ws), ignore_border=True,
                               padding=pad, mode=mode)
            utt.verify_grad(fn, [data], mode=mode_with_gpu)
            # Confirm that the opt would have inserted it.
            fg = theano.function([x], theano.grad(fn(x).sum(), x),
                                 mode=mode_with_gpu)
            assert any([isinstance(node.op, dnn.GpuDnnPoolGrad)
                        for node in fg.maker.fgraph.toposort()])

            # Test the GPU grad + GPU implementation
            def fn(x):
                dnn_op = dnn.dnn_pool(
                    x, ws=(ws, ws),
                    stride=(stride, stride),
                    pad=pad,
                    mode=mode)
                return dnn_op
            utt.verify_grad(fn, [data], mode=mode_with_gpu)
            # Confirm that we get the good op.
            fg = theano.function([x], theano.grad(fn(x).sum(), x),
                                 mode=mode_with_gpu)
            assert any([isinstance(node.op, dnn.GpuDnnPoolGrad)
                        for node in fg.maker.fgraph.toposort()])
            g_out = fg(data)

            # Compare against the CPU result
            out = pool_2d(x, (ws, ws),
                          padding=pad,
                          ignore_border=True, mode=mode)
            fc = theano.function([x], theano.grad(out.sum(), x),
                                 mode=mode_without_gpu)
            if mode == 'max':
                assert any([isinstance(node.op, MaxPoolGrad)
                            for node in fc.maker.fgraph.toposort()])
            else:
                assert any([isinstance(node.op, AveragePoolGrad)
                            for node in fc.maker.fgraph.toposort()])
            c_out = fc(data)
            utt.assert_allclose(c_out, g_out)


def test_pooling_3d():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)

    # 'average_exc_pad' is disabled for versions < 4004
    if dnn.version(raises=False) < 4004:
        modes = ('max', 'average_inc_pad')
    else:
        modes = ('max', 'average_inc_pad', 'average_exc_pad')

    x = T.ftensor5()
    for mode, pad in product(modes,
                             ((0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1),
                              (3, 2, 2), (2, 3, 2), (2, 2, 3))):
        if mode == 'max':
            func = T.max
        else:
            func = T.mean

        if pad != (0, 0, 0) and func is T.mean:
            continue

        for ws in (4, 2, 5):
            for stride in (2, 3):
                if stride > ws:
                    continue
                if pad[0] > stride or pad[1] > stride or pad[2] > stride:
                    # Not implemented
                    continue
                # We will check that the opt introduced it.
                out1 = pool_3d(x, (ws, ws, ws),
                               st=(stride, stride, stride),
                               ignore_border=True,
                               padding=pad, mode=mode)
                out2 = pool3d2d(x, ds=(ws, ws, ws), strides=(stride, stride, stride),
                                pad=pad,
                                pool_function=func)
                mode_without_gpu2 = mode_without_gpu.including()
                mode_without_gpu2.check_isfinite = False
                f1 = theano.function([x], out1, mode=mode_with_gpu)
                assert any([isinstance(node.op, dnn.GpuDnnPool)
                            for node in f1.maker.fgraph.apply_nodes])
                f2 = theano.function([x], out2, mode=mode_without_gpu2)
                assert not any([isinstance(node.op, dnn.GpuDnnPool)
                                for node in f2.maker.fgraph.apply_nodes])
                for shp in [(1, 10, 30, 30, 30),
                            (1, 3, 29, 29, 29),
                            (3, 1, 47, 97, 47),
                            ]:
                    data = numpy.random.normal(0, 1, shp).astype("float32")
                    a = f1(data)
                    b = f2(data)

                    utt.assert_allclose(a, b)

        # Test the grad
        for shp in [(1, 1, 2, 2, 2),
                    (1, 1, 3, 3, 3)]:
            data = numpy.random.normal(0, 1, shp).astype("float32") * 10

            ws = 2
            stride = 2
            if pad[0] > stride or pad[1] > stride or pad[2] > stride:
                # Not implemented
                continue

            # This test the CPU grad + opt + GPU implemtentation
            def fn(x):
                return pool_3d(x, (ws, ws, ws), ignore_border=True,
                               padding=pad, mode=mode)
            utt.verify_grad(fn, [data], mode=mode_with_gpu)
            # Confirm that the opt would have inserted it.
            fg = theano.function([x], theano.grad(fn(x).sum(), x),
                                 mode=mode_with_gpu)
            assert any([isinstance(node.op, dnn.GpuDnnPoolGrad)
                        for node in fg.maker.fgraph.toposort()])

            # Test the GPU grad + GPU implementation
            def fn(x):
                dnn_op = dnn.dnn_pool(
                    x, ws=(ws, ws, ws),
                    stride=(stride, stride, stride),
                    pad=pad,
                    mode=mode)
                return dnn_op
            utt.verify_grad(fn, [data], mode=mode_with_gpu)
            # Confirm that we get the good op.
            fg = theano.function([x], theano.grad(fn(x).sum(), x),
                                 mode=mode_with_gpu)
            assert any([isinstance(node.op, dnn.GpuDnnPoolGrad)
                        for node in fg.maker.fgraph.toposort()])
            g_out = fg(data)

            # Compare against the CPU result
            out = pool_3d(x, (ws, ws, ws),
                          padding=pad,
                          ignore_border=True, mode=mode)
            fc = theano.function([x], theano.grad(out.sum(), x),
                                 mode=mode_without_gpu)
            if mode == 'max':
                assert any([isinstance(node.op, MaxPoolGrad)
                            for node in fc.maker.fgraph.toposort()])
            else:
                assert any([isinstance(node.op, AveragePoolGrad)
                            for node in fc.maker.fgraph.toposort()])
            c_out = fc(data)
            utt.assert_allclose(c_out, g_out)


def test_pooling_with_tensor_vars():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    x = T.ftensor4()
    ws = theano.shared(numpy.array([2, 2], dtype='int32'))
    st = theano.shared(numpy.array([1, 1], dtype='int32'))
    pad = theano.shared(numpy.array([0, 0], dtype='int32'))
    mode = 'max'

    def fn(x):
        dnn_op = dnn.dnn_pool(x,
                              ws=ws,
                              stride=st,
                              pad=pad,
                              mode=mode)
        return dnn_op

    for shp in [(1, 1, 2, 2),
                (1, 1, 3, 3)]:
        data = numpy.random.normal(0, 1, shp).astype("float32") * 10
        theano.tests.unittest_tools.verify_grad(
            fn, [data], mode=mode_with_gpu)

    out2 = pool_2d_i2n(x, ds=(2, 2), strides=(1, 1),
                       pad=(0, 0),
                       pool_function=T.max)

    mode_without_gpu2 = mode_without_gpu.including()
    mode_without_gpu2.check_isfinite = False

    f1 = theano.function([x], fn(x), mode=mode_with_gpu)
    assert any([isinstance(node.op, dnn.GpuDnnPool)
                for node in f1.maker.fgraph.apply_nodes])
    f2 = theano.function([x], out2, mode=mode_without_gpu2)
    assert not any([isinstance(node.op, dnn.GpuDnnPool)
                    for node in f2.maker.fgraph.apply_nodes])
    for shp in [(1, 10, 100, 100),
                (1, 3, 99, 99),
                (32, 1, 147, 197),
                ]:
        data = numpy.random.normal(0, 1, shp).astype("float32")
        a = f1(data).__array__()

        b = f2(data).__array__()
        utt.assert_allclose(a, b)


def test_pooling_opt():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)

    # 2D pooling
    x = T.fmatrix()

    f = theano.function(
        [x],
        pool_2d(x, ds=(2, 2), mode='average_inc_pad',
                ignore_border=True),
        mode=mode_with_gpu)

    assert any([isinstance(n.op, dnn.GpuDnnPool)
                for n in f.maker.fgraph.toposort()])

    f(numpy.zeros((10, 10), dtype='float32'))

    # gradient of 2D pooling
    f = theano.function(
        [x],
        T.grad(pool_2d(x, ds=(2, 2), mode='average_inc_pad',
                       ignore_border=True).sum(),
               x),
        mode=mode_with_gpu.including("cudnn"))

    assert any([isinstance(n.op, dnn.GpuDnnPoolGrad)
                for n in f.maker.fgraph.toposort()])

    f(numpy.zeros((10, 10), dtype='float32'))

    # Test sum pooling
    f = theano.function(
        [x],
        pool_2d(x, ds=(2, 3), mode='sum',
                ignore_border=True),
        mode=mode_with_gpu)
    data = numpy.random.rand(10, 10).astype('float32')
    f(data)

    # 3D pooling
    x = T.ftensor3()

    f = theano.function(
        [x],
        pool_3d(x, ds=(2, 2, 2), mode='average_inc_pad',
                ignore_border=True),
        mode=mode_with_gpu)

    assert any([isinstance(n.op, dnn.GpuDnnPool)
                for n in f.maker.fgraph.toposort()])

    f(numpy.zeros((10, 10, 10), dtype='float32'))

    # gradient of 3D pooling
    f = theano.function(
        [x],
        T.grad(pool_3d(x, ds=(2, 2, 2), mode='average_inc_pad',
                       ignore_border=True).sum(),
               x),
        mode=mode_with_gpu.including("cudnn"))

    assert any([isinstance(n.op, dnn.GpuDnnPoolGrad)
                for n in f.maker.fgraph.toposort()])

    f(numpy.zeros((10, 10, 10), dtype='float32'))


def test_pooling_opt_arbitrary_dimensions():
    # test if input with an arbitrary number of non-pooling dimensions
    # is correctly reshaped to run on the GPU

    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)

    # 'average_exc_pad' is disabled for versions < 4004
    if dnn.version(raises=False) < 4004:
        modes = ('max', 'average_inc_pad')
    else:
        modes = ('max', 'average_inc_pad', 'average_exc_pad')

    for n_non_pool_dims in (0, 1, 2, 3):
        for ws in ((2, 2), (3, 3, 3)):
            # create input shape: non-pooling dimensions
            # followed by 2 or 3 pooling dimensions
            shp = (2,) * n_non_pool_dims + (5,) * len(ws)
            data = numpy.random.normal(0, 1, shp).astype('float32')
            input = gpuarray_shared_constructor(data)

            for mode in modes:
                out_pool = Pool(ndim=len(ws), mode=mode, ignore_border=True)(input, ws)
                out_pool_grad = T.grad(T.sum(out_pool), wrt=input)
                out = [out_pool, out_pool_grad]

                # run on GPU
                fg = theano.function([], out, mode=mode_with_gpu)
                assert any([isinstance(node.op, dnn.GpuDnnPool)
                           for node in fg.maker.fgraph.toposort()])
                assert any([isinstance(node.op, dnn.GpuDnnPoolGrad)
                           for node in fg.maker.fgraph.toposort()])
                res_gpu = fg()

                # run on CPU
                fc = theano.function([], out, mode=mode_without_gpu)
                assert any([isinstance(node.op, Pool)
                           for node in fc.maker.fgraph.toposort()])
                if mode == 'max':
                    assert any([isinstance(node.op, MaxPoolGrad)
                               for node in fc.maker.fgraph.toposort()])
                else:
                    assert any([isinstance(node.op, AveragePoolGrad)
                               for node in fc.maker.fgraph.toposort()])
                res_cpu = fg()

                # check for similarity
                utt.assert_allclose(res_gpu[0], res_cpu[0])
                utt.assert_allclose(res_gpu[1], res_cpu[1])


def test_dnn_tag():
    """
    Test that if cudnn isn't avail we crash and that if it is avail, we use it.
    """
    x = T.ftensor4()
    old = theano.config.on_opt_error
    theano.config.on_opt_error = "raise"

    sio = StringIO()
    handler = logging.StreamHandler(sio)
    logging.getLogger('theano.compile.tests.test_dnn').addHandler(handler)
    # Silence original handler when intentionnally generating warning messages
    logging.getLogger('theano').removeHandler(theano.logging_default_handler)
    raised = False
    try:
        f = theano.function(
            [x],
            pool_2d(x, ds=(2, 2), ignore_border=True),
            mode=mode_with_gpu.including("cudnn"))
    except (AssertionError, RuntimeError):
        assert not dnn.dnn_available(test_ctx_name)
        raised = True
    finally:
        theano.config.on_opt_error = old
        logging.getLogger(
            'theano.compile.tests.test_dnn').removeHandler(handler)
        logging.getLogger('theano').addHandler(theano.logging_default_handler)

    if not raised:
        assert dnn.dnn_available(test_ctx_name)
        assert any([isinstance(n.op, dnn.GpuDnnPool)
                    for n in f.maker.fgraph.toposort()])


class TestDnnInferShapes(utt.InferShapeTester):

    border_modes = ['valid', 'full', 'half']
    conv_modes = ['conv', 'cross']

    def setUp(self):
        super(TestDnnInferShapes, self).setUp()
        self.mode = mode_with_gpu

    def test_softmax(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)
        t = T.ftensor4('t')
        rand_tensor = numpy.asarray(
            numpy.random.rand(5, 4, 3, 2),
            dtype='float32'
        )
        self._compile_and_check(
            [t],
            [dnn.GpuDnnSoftmax('accurate', 'channel')(t)],
            [rand_tensor],
            dnn.GpuDnnSoftmax
        )

        self._compile_and_check(
            [t],
            [
                T.grad(
                    dnn.GpuDnnSoftmax(
                        'accurate',
                        'channel'
                    )(t).mean(),
                    t
                )
            ],
            [rand_tensor],
            dnn.GpuDnnSoftmaxGrad
        )

    def _test_conv(self, img, kerns, out, img_val, kern_vals, border_mode, conv_mode, subsamples, algo):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)

        img_val = numpy.asarray(img_val, dtype='float32')
        kern_vals = numpy.asarray(kern_vals, dtype='float32')

        for subsample in subsamples:
            out_vals = numpy.zeros(
                dnn.GpuDnnConv.get_out_shape(img_val.shape, kern_vals.shape,
                                             border_mode=border_mode,
                                             subsample=subsample),
                dtype='float32')
            desc = dnn.GpuDnnConvDesc(
                border_mode=border_mode,
                subsample=subsample,
                conv_mode=conv_mode
            )(kerns.shape)
            conv = dnn.GpuDnnConv(algo=algo)(img, kerns, out, desc)
            self._compile_and_check(
                [img, kerns, out],
                [conv],
                [img_val, kern_vals, out_vals],
                dnn.GpuDnnConv
            )

    @parameterized.expand(chain(product([SUPPORTED_DNN_CONV_ALGO_FWD[0]],
                                        border_modes,
                                        conv_modes),
                                product(SUPPORTED_DNN_CONV_ALGO_FWD[1:],
                                        [border_modes[0]],
                                        [conv_modes[0]])),
                          testcase_func_name=utt.custom_name_func)
    def test_conv(self, algo, border_mode, conv_mode):
        if algo == 'winograd' and dnn.version(raises=False) < 5000:
            raise SkipTest(dnn.dnn_available.msg)

        self._test_conv(T.ftensor4('img'),
                        T.ftensor4('kerns'),
                        T.ftensor4('out'),
                        numpy.random.rand(7, 2, 8, 4),
                        numpy.random.rand(8, 2, 4, 3),
                        border_mode,
                        conv_mode,
                        [(1, 1), (2, 2)],
                        algo)

    @parameterized.expand(product(border_modes, conv_modes), utt.custom_name_func)
    def test_conv3d_none(self, border_mode, conv_mode):
        self._test_conv(T.ftensor5('img'),
                        T.ftensor5('kerns'),
                        T.ftensor5('out'),
                        numpy.random.rand(10, 2, 6, 4, 11),
                        numpy.random.rand(8, 2, 4, 3, 1),
                        border_mode,
                        conv_mode,
                        [(1, 1, 1), (2, 2, 2)],
                        'none')

    def _test_conv_gradw(self, img, kerns, out, img_val, kern_vals, border_mode, conv_mode, subsample):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)

        img_val = numpy.asarray(
            img_val,
            dtype='float32'
        )
        kern_vals = numpy.asarray(
            kern_vals,
            dtype='float32'
        )

        temp_img = img.dimshuffle(1, 0, 2, 3)
        temp_kerns = kerns
        if conv_mode == 'conv':
            temp_kerns = temp_kerns[:, :, ::-1, ::-1]
        temp_kerns = temp_kerns.dimshuffle(1, 0, 2, 3)
        shape = (
            kern_vals.shape[1], img_val.shape[1],
            img_val.shape[2] - kern_vals.shape[2] + 1,
            img_val.shape[3] - kern_vals.shape[3] + 1
        )
        out_vals = numpy.zeros(shape, dtype='float32')
        desc = dnn.GpuDnnConvDesc(
            border_mode=border_mode,
            subsample=subsample,
            conv_mode=conv_mode
        )(out.shape)
        conv_grad_w = dnn.GpuDnnConvGradW()(
            temp_img,
            temp_kerns,
            out,
            desc,
        )
        self._compile_and_check(
            [temp_img, temp_kerns, out],
            [conv_grad_w],
            [img_val, kern_vals, out_vals],
            dnn.GpuDnnConvGradW
        )

    @parameterized.expand(product(border_modes, conv_modes), utt.custom_name_func)
    def test_conv_gradw(self, border_mode, conv_mode):
        self._test_conv_gradw(T.ftensor4('img'),
                              T.ftensor4('kerns'),
                              T.ftensor4('out'),
                              numpy.random.rand(2, 5, 6, 8),
                              numpy.random.rand(2, 1, 5, 6),
                              border_mode,
                              conv_mode,
                              (1, 1))

    def test_conv_gradi(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)
        img = T.ftensor4('img')
        kerns = T.ftensor4('kerns')
        out = T.ftensor4('out')
        kern_vals = numpy.asarray(
            numpy.random.rand(13, 14, 15, 16),
            dtype='float32'
        )
        out_vals = numpy.asarray(
            numpy.random.rand(3, 13, 5, 6),
            dtype='float32'
        )

        for params in product(
            ['valid'],  # Should this work for 'full'?
            [(1, 1)],
            ['conv', 'cross']
        ):
            shape = (
                out_vals.shape[0], kern_vals.shape[1],
                out_vals.shape[2] + kern_vals.shape[2] - 1,
                out_vals.shape[3] + kern_vals.shape[3] - 1
            )
            img_vals = numpy.zeros(shape, dtype='float32')
            desc = dnn.GpuDnnConvDesc(
                border_mode=params[0],
                subsample=params[1],
                conv_mode=params[2]
            )(kerns.shape)
            conv_grad_i = dnn.GpuDnnConvGradI()(
                kerns,
                out,
                img,
                desc,
            )
            self._compile_and_check(
                [kerns, img, out],
                [conv_grad_i],
                [kern_vals, img_vals, out_vals],
                dnn.GpuDnnConvGradI
            )

    def test_pool(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)
        img = T.ftensor4('img')
        img_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5),
            dtype='float32'
        )

        # 'average_exc_pad' is disabled for versions < 4004
        if dnn.version(raises=False) < 4004:
            modes = ['max', 'average_inc_pad']
        else:
            modes = ['max', 'average_inc_pad', 'average_exc_pad']

        for params in product(
            [(1, 1), (2, 2), (3, 3)],
            [(1, 1), (2, 2), (3, 3)],
            modes
        ):
            self._compile_and_check(
                [img],
                [dnn.GpuDnnPool(mode=params[2])(img, params[0], params[1], (0, 0))],
                [img_val],
                dnn.GpuDnnPool
            )

    def test_pool_3d(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)
        img = T.ftensor5('img')
        img_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5, 6),
            dtype='float32'
        )

        # 'average_exc_pad' is disabled for versions < 4004
        if dnn.version(raises=False) < 4004:
            modes = ['max', 'average_inc_pad']
        else:
            modes = ['max', 'average_inc_pad', 'average_exc_pad']

        for params in product(
            [(1, 1, 1), (2, 2, 2), (3, 3, 3)],
            [(1, 1, 1), (2, 2, 2), (3, 3, 3)],
            modes
        ):
            self._compile_and_check(
                [img],
                [dnn.GpuDnnPool(mode=params[2])(img, params[0], params[1], (0, 0, 0))],
                [img_val],
                dnn.GpuDnnPool
            )

    def test_pool_grad(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)
        img = T.ftensor4('img')
        img_grad = T.ftensor4('img_grad')
        out = T.ftensor4('out')
        img_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5),
            dtype='float32'
        )
        img_grad_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5),
            dtype='float32'
        )
        out_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5),
            dtype='float32'
        )

        for params in product(
            [(1, 1), (2, 2), (3, 3)],
            [(1, 1), (2, 2), (3, 3)],
            ['max', 'average_inc_pad']
        ):
            pool_grad = dnn.GpuDnnPoolGrad(mode=params[2])(
                img,
                out,
                img_grad,
                params[0],
                params[1],
                (0, 0)
            )
            self._compile_and_check(
                [img, img_grad, out],
                [pool_grad],
                [img_val, img_grad_val, out_val],
                dnn.GpuDnnPoolGrad
            )

    def test_pool_3d_grad(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)
        img = T.ftensor5('img')
        img_grad = T.ftensor5('img_grad')
        out = T.ftensor5('out')
        img_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5, 6),
            dtype='float32'
        )
        img_grad_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5, 6),
            dtype='float32'
        )
        out_val = numpy.asarray(
            numpy.random.rand(2, 3, 4, 5, 6),
            dtype='float32'
        )

        for params in product(
            [(1, 1, 1), (2, 2, 2), (3, 3, 3)],
            [(1, 1, 1), (2, 2, 2), (3, 3, 3)],
            ['max', 'average_inc_pad']
        ):
            pool_grad = dnn.GpuDnnPoolGrad(mode=params[2])(
                img,
                out,
                img_grad,
                params[0],
                params[1],
                (0, 0, 0)
            )
            self._compile_and_check(
                [img, img_grad, out],
                [pool_grad],
                [img_val, img_grad_val, out_val],
                dnn.GpuDnnPoolGrad
            )


# this has been a problem in the past
def test_dnn_conv_border_mode():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    img = T.ftensor4()
    kern = T.ftensor4()

    dnn.dnn_conv(img, kern, border_mode=1)
    dnn.dnn_conv(img, kern, border_mode=(2, 3))
    dnn.dnn_conv(img, kern, border_mode='full')
    dnn.dnn_conv(img, kern, border_mode='valid')
    dnn.dnn_conv(img, kern, border_mode='half')


def test_dnn_conv_alpha_output_merge():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    img = T.ftensor4()
    kern = T.ftensor4()
    out = T.ftensor4()

    b = 1
    c = 4
    f = 3
    ih = 5
    iw = 8
    kh = 2
    kw = 6
    img_val = numpy.random.random((b, c, ih, iw)).astype('float32')
    kern_val = numpy.random.random((f, c, kh, kw)).astype('float32')
    out_val = numpy.random.random((b, f, ih - kh + 1,
                                   iw - kw + 1)).astype('float32')

    conv = dnn.dnn_conv(img, kern)
    gw = theano.grad(conv.sum(), kern)
    gi = theano.grad(conv.sum(), img)

    lr = numpy.asarray(0.05, dtype='float32')

    fr = lr * (conv + out)
    wr = kern + lr * gw
    ir = img + lr * gi

    f1 = theano.function([img, kern, out], [fr, wr, ir], mode=mode_with_gpu)
    assert isinstance(f1.maker.fgraph.outputs[0].owner.inputs[0].owner.op,
                      dnn.GpuDnnConv)
    assert isinstance(f1.maker.fgraph.outputs[1].owner.inputs[0].owner.op,
                      dnn.GpuDnnConvGradW)
    assert isinstance(f1.maker.fgraph.outputs[2].owner.inputs[0].owner.op,
                      dnn.GpuDnnConvGradI)

    mode = mode_with_gpu
    mode = mode.excluding('local_dnn_conv_alpha_merge')
    mode = mode.excluding('local_dnn_convw_alpha_merge')
    mode = mode.excluding('local_dnn_convi_alpha_merge')
    mode = mode.excluding('local_dnn_conv_output_merge')
    mode = mode.excluding('local_dnn_convw_output_merge')
    mode = mode.excluding('local_dnn_convi_output_merge')

    f2 = theano.function([img, kern, out], [fr, wr, ir], mode=mode)

    assert not isinstance(f2.maker.fgraph.outputs[0].owner.inputs[0].owner.op,
                          dnn.GpuDnnConv)
    assert not isinstance(f2.maker.fgraph.outputs[1].owner.inputs[0].owner.op,
                          dnn.GpuDnnConvGradW)
    assert not isinstance(f2.maker.fgraph.outputs[2].owner.inputs[0].owner.op,
                          dnn.GpuDnnConvGradI)

    out_f1 = f1(img_val, kern_val, out_val)
    out_f2 = f2(img_val, kern_val, out_val)

    assert len(out_f1) == len(out_f2)

    for v1, v2 in zip(out_f1, out_f2):
        utt.assert_allclose(v1, v2)


def test_dnn_conv_grad():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    b = 1
    c = 4
    f = 3
    ih = 2
    iw = 8
    kh = 2
    kw = 2
    img_val = numpy.random.random((b, c, ih, iw)).astype('float32')
    kern_val = numpy.random.random((f, c, kh, kw)).astype('float32')
    out_val = numpy.random.random((b, f, ih - kw + 1,
                                   iw - kw + 1)).astype('float32')

    def dconv(img, kern, out):
        desc = dnn.GpuDnnConvDesc(border_mode='valid', subsample=(1, 1),
                                  conv_mode='conv')(kern.shape)
        return dnn.GpuDnnConv()(img, kern, out, desc, alpha=0.5, beta=0.75)

    def dconvi(img, kern, out):
        desc = dnn.GpuDnnConvDesc(border_mode='valid', subsample=(1, 1),
                                  conv_mode='conv')(kern.shape)
        return dnn.GpuDnnConvGradI()(kern, out, img, desc, alpha=-1.0,
                                     beta=0.0)

    def dconvw(img, kern, out):
        desc = dnn.GpuDnnConvDesc(border_mode='valid', subsample=(1, 1),
                                  conv_mode='conv')(kern.shape)
        return dnn.GpuDnnConvGradW()(img, out, kern, desc, alpha=0.75,
                                     beta=-1.0)

    utt.verify_grad(dconv, [img_val, kern_val, out_val])
    utt.verify_grad(dconvi, [img_val, kern_val, out_val])
    utt.verify_grad(dconvw, [img_val, kern_val, out_val])


def test_version():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    assert isinstance(dnn.version(), int)


class test_SoftMax(test_nnet.test_SoftMax):
    gpu_op = dnn.GpuDnnSoftmax
    gpu_grad_op = dnn.GpuDnnSoftmaxGrad
    mode = mode_with_gpu

    def setUp(self):
        if not dnn.dnn_available(test_ctx_name):
            raise SkipTest(dnn.dnn_available.msg)

    def test_softmax_shape_0(self):
        raise SkipTest("Cudnn doesn't support 0 shapes")

    def test_softmax_grad(self):
        def cmp(n, m, f, f_gpu):
            data = numpy.arange(n * m, dtype='float32').reshape(n, m)
            gdata = numpy.asarray(data)[:, :, None, None]

            out = f(data)
            gout = numpy.asarray(f_gpu(gdata))[:, :, 0, 0]
            utt.assert_allclose(out, gout)

        x = T.matrix('x', 'float32')
        x_gpu = T.tensor4('x_gpu', 'float32')
        f_z = T.nnet.softmax_op
        f_gpu = dnn.GpuDnnSoftmax(
            'accurate',
            'channel'
        )

        # Verify the grad operation
        dims = (2, 3, 4, 5)
        gdata = numpy.arange(
            numpy.product(dims),
            dtype='float32'
        ).reshape(dims)
        T.verify_grad(f_gpu, [gdata], rng=numpy.random,
                      mode=mode_with_gpu)

        # Verify that the CPU and GPU implementations return the same results
        # up to a tolerance.

        self._test_softmax(
            x,
            x_gpu,
            f_z,
            f_gpu,
            cmp
        )

        self._test_softmax(
            x, x, f_z, f_z, self._cmp
        )

        # Verify that the SoftmaxGrad -> Gpu[Dnn]SoftmaxGrad
        # optimization is applied when cudnn is required
        y = T.fvector('y')
        f = theano.function(
            [y],
            T.grad(T.nnet.softmax(y).mean(), y),
            mode=mode_with_gpu
        )
        sorted_f = f.maker.fgraph.toposort()
        val = numpy.random.rand(5).astype('float32')
        out_dnn = f(val)
        assert(len([i
                    for i in sorted_f
                    if isinstance(
                        i.op,
                        self.gpu_grad_op)
                    ]) == 1)
        assert(len([i
                    for i in sorted_f
                    if isinstance(
                        i.op,
                        theano.tensor.nnet.SoftmaxGrad)
                    ]) == 0)

        # Verify that the SoftmaxGrad -> Gpu[Dnn]SoftmaxGrad
        # optimization is not applied when cudnn is excluded or not
        # available
        mode_wo_cudnn = mode_with_gpu.excluding("cudnn")
        y = T.fvector('y')
        f = theano.function(
            [y],
            T.grad(T.nnet.softmax(y).mean(), y),
            mode=mode_wo_cudnn
        )
        sorted_f = f.maker.fgraph.toposort()
        out_cpu = f(val)
        utt.assert_allclose(out_dnn, out_cpu)
        assert(len([i
                    for i in sorted_f
                    if isinstance(
                        i.op,
                        self.gpu_grad_op)
                    ]) == 0)
        assert(len([i
                    for i in sorted_f
                    if isinstance(
                        i.op,
                        theano.tensor.nnet.SoftmaxGrad)
                    ]) == 1)

        # Verify that the SoftmaxGrad -> GpuDnnSoftmaxGrad do not
        # crash with manual graph
        y = T.fvector('y')
        o = theano.tensor.nnet.SoftmaxGrad()(y, y * 2)
        f = theano.function([y], o, mode=mode_with_gpu)
        sorted_f = f.maker.fgraph.toposort()
        assert(len([i
                    for i in sorted_f
                    if isinstance(
                        i.op,
                        self.gpu_grad_op)
                    ]) == 1)
        assert(len([i
                    for i in sorted_f
                    if isinstance(
                        i.op,
                        theano.tensor.nnet.SoftmaxGrad)
                    ]) == 0)

    def test_log_softmax(self):
        # This is a test for an optimization that depends on cuDNN v3 or
        # more recent. Don't test if the cuDNN version is too old.
        if dnn.version(raises=False) < 3000:
            raise SkipTest("Log-softmax is only in cudnn v3+")

        x = T.ftensor4()
        softmax_out = dnn.GpuDnnSoftmax('accurate', 'channel')(x)
        log_out = T.log(T.as_tensor_variable(softmax_out))

        f = theano.function([x], log_out, mode=mode_with_gpu)

        # Ensure that the optimization has been applied
        dnn_softmax_nodes = [n for n in f.maker.fgraph.toposort() if
                             isinstance(n.op, dnn.GpuDnnSoftmax)]
        assert len(dnn_softmax_nodes) == 1
        assert dnn_softmax_nodes[0].op.algo == "log"

        # Ensure that the output of the function is valid
        input_shapes = [(3, 4, 5, 6),
                        (1025, 2, 3, 4),
                        (2, 1025, 3, 4),
                        (2, 3, 1025, 4),
                        (2, 3, 4, 1025),
                        (66000, 2, 3, 4),
                        (2, 66000, 3, 4),
                        (2, 3, 66000, 4),
                        (2, 3, 4, 66000)]

        for inp_shape in input_shapes:
            input_val = numpy.random.normal(0, 1, inp_shape).astype("float32")

            out = f(input_val)
            expected_out = numpy.log(numpy.exp(input_val) /
                                     numpy.exp(input_val).sum(1)[:, None, :, :])

            utt.assert_allclose(out, expected_out)

    def test_log_softmax2(self):
        # Test that the op LogSoftmax is correctly replaced by the op
        # DnnSoftmax with the 'log' mode.

        # This is a test for an optimization that depends on cuDNN v3 or
        # more recent. Don't test if the cuDNN version is too old.
        if dnn.version(raises=False) < 3000:
            raise SkipTest("Log-softmax is only in cudnn v3+")

        # Compile a reference function, on the CPU, to be used to validate the
        # results of the other function.
        x = T.fmatrix()
        f_ref = theano.function([x], T.nnet.LogSoftmax()(x))

        # Build the first graph and ensure that the optimization is applied
        log_softmax_out = T.nnet.LogSoftmax()(x)
        f = theano.function([x], log_softmax_out, mode=mode_with_gpu)

        dnn_softmax_nodes = [n for n in f.maker.fgraph.toposort() if
                             isinstance(n.op, dnn.GpuDnnSoftmax)]
        assert len(dnn_softmax_nodes) == 1
        assert dnn_softmax_nodes[0].op.algo == "log"

        # Compare the output of the function with the reference function
        inp = numpy.random.normal(0, 1, (5, 6)).astype("float32")
        utt.assert_allclose(f(inp), f_ref(inp))

        # Build the first graph and ensure that the optimization is applied
        log_softmax_out = T.log(T.nnet.Softmax()(x))
        f = theano.function([x], log_softmax_out, mode=mode_with_gpu)

        dnn_softmax_nodes = [n for n in f.maker.fgraph.toposort() if
                             isinstance(n.op, dnn.GpuDnnSoftmax)]
        assert len(dnn_softmax_nodes) == 1
        assert dnn_softmax_nodes[0].op.algo == "log"

        # Compare the output of the function with the reference function
        inp = numpy.random.normal(0, 1, (5, 6)).astype("float32")
        utt.assert_allclose(f(inp), f_ref(inp))


def test_dnn_batchnorm_train():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    if dnn.version(raises=False) < 5000:
        raise SkipTest("batch normalization requires cudnn v5+")
    utt.seed_rng()

    for mode in ('per-activation', 'spatial'):
        for vartype in (T.ftensor4, T.ftensor3, T.fmatrix, T.fvector):
            x, scale, bias = (vartype(n) for n in ('x', 'scale', 'bias'))
            ndim = x.ndim
            eps = 5e-3  # some non-standard value to test if it's used

            # forward pass
            out, x_mean, x_invstd = dnn.dnn_batch_normalization_train(
                x, scale, bias, mode, eps)
            # reference forward pass
            if mode == 'per-activation':
                axes = (0,)
            elif mode == 'spatial':
                axes = (0,) + tuple(range(2, ndim))
            x_mean2 = x.mean(axis=axes, keepdims=True)
            x_invstd2 = T.inv(T.sqrt(x.var(axis=axes, keepdims=True) + eps))
            scale2 = T.addbroadcast(scale, *axes)
            bias2 = T.addbroadcast(bias, *axes)
            out2 = (x - x_mean2) * (scale2 * x_invstd2) + bias2
            # backward pass
            dy = vartype('dy')
            grads = T.grad(None, wrt=[x, scale, bias], known_grads={out: dy})
            # reference backward pass
            grads2 = T.grad(None, wrt=[x, scale, bias], known_grads={out2: dy})
            # compile
            f = theano.function([x, scale, bias, dy],
                                [out, x_mean, x_invstd, out2, x_mean2, x_invstd2] +
                                grads + grads2, mode=mode_with_gpu)
            # run
            for data_shape in ((10, 20, 30, 40), (4, 3, 1, 1), (1, 1, 5, 5)):
                data_shape = data_shape[:ndim]
                param_shape = tuple(1 if d in axes else s
                                    for d, s in enumerate(data_shape))
                X = 4 + 3 * numpy.random.randn(*data_shape).astype('float32')
                Dy = -1 + 2 * numpy.random.randn(*data_shape).astype('float32')
                Scale = numpy.random.randn(*param_shape).astype('float32')
                Bias = numpy.random.randn(*param_shape).astype('float32')
                outputs = f(X, Scale, Bias, Dy)
                # compare outputs
                utt.assert_allclose(outputs[0], outputs[0 + 3])  # out
                utt.assert_allclose(outputs[1], outputs[1 + 3])  # mean
                utt.assert_allclose(outputs[2], outputs[2 + 3])  # invstd
                # compare gradients
                utt.assert_allclose(outputs[6], outputs[6 + 3])  # dx
                utt.assert_allclose(outputs[7], outputs[7 + 3], rtol=3e-3)  # dscale
                utt.assert_allclose(outputs[8], outputs[8 + 3])  # dbias


def test_batchnorm_inference():
    if not dnn.dnn_available(test_ctx_name):
        raise SkipTest(dnn.dnn_available.msg)
    if dnn.version(raises=False) < 5000:
        raise SkipTest("batch normalization requires cudnn v5+")
    utt.seed_rng()

    for mode in ('per-activation', 'spatial'):
        for vartype in (T.ftensor4, T.ftensor3, T.fmatrix, T.fvector):
            x, scale, bias, mean, var = (vartype(n) for n in ('x', 'scale',
                                                              'bias', 'mean',
                                                              'var'))
            ndim = x.ndim
            eps = 5e-3  # some non-standard value to test if it's used

            # forward pass
            out = dnn.dnn_batch_normalization_test(x, scale, bias, mean,
                                                   var, mode, eps)
            # reference forward pass
            if mode == 'per-activation':
                axes = (0,)
            elif mode == 'spatial':
                axes = (0,) + tuple(range(2, ndim))
            scale2, bias2, mean2, var2 = (T.addbroadcast(t, *axes)
                                          for t in (scale, bias, mean, var))
            out2 = (x - mean2) * (scale2 / T.sqrt(var2 + eps)) + bias2
            # backward pass
            dy = vartype('dy')
            grads = T.grad(None, wrt=[x, scale, bias, mean, var], known_grads={out: dy})
            # reference backward pass
            grads2 = T.grad(None, wrt=[x, scale, bias, mean, var], known_grads={out2: dy})
            # compile
            f = theano.function([x, scale, bias, mean, var, dy],
                                [out, out2] + grads + grads2, mode=mode_with_gpu)
            # run
            for data_shape in ((10, 20, 30, 40), (4, 3, 1, 1), (1, 1, 5, 5)):
                data_shape = data_shape[:ndim]
                param_shape = tuple(1 if d in axes else s
                                    for d, s in enumerate(data_shape))
                X = 4 + 3 * numpy.random.randn(*data_shape).astype('float32')
                Dy = -1 + 2 * numpy.random.randn(*data_shape).astype('float32')
                Scale = numpy.random.randn(*param_shape).astype('float32')
                Bias = numpy.random.randn(*param_shape).astype('float32')
                Mean = numpy.random.randn(*param_shape).astype('float32')
                Var = numpy.random.rand(*param_shape).astype('float32')
                outputs = f(X, Scale, Bias, Mean, Var, Dy)
                # compare outputs
                utt.assert_allclose(outputs[0], outputs[1])  # out
                # compare gradients
                utt.assert_allclose(outputs[2], outputs[2 + 5])  # dx
                utt.assert_allclose(outputs[3], outputs[3 + 5])  # dscale
                utt.assert_allclose(outputs[4], outputs[4 + 5])  # dbias
                utt.assert_allclose(outputs[5], outputs[5 + 5])  # dmean
                utt.assert_allclose(outputs[6], outputs[6 + 5], atol=2e-5)  # dvar
