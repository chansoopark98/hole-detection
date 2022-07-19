from tensorflow.keras import backend as K
from tensorflow.keras import losses
import tensorflow as tf
import tensorflow_addons as tfa
import itertools
from typing import Any, Optional
from tensorflow.keras.losses import SparseCategoricalCrossentropy, Reduction
from tensorflow.keras.layers import Flatten
import tensorflow as tf

_EPSILON = tf.keras.backend.epsilon()


class DistributeLoss():
    def __init__(self, image_size, num_classes, global_batch_size):
        self.image_size = image_size
        self.num_classes = num_classes
        self.global_batch_size = global_batch_size
        self.tversky_smooth = 0.000001
        self.tversky_focal_gamma = 0.75

    
    def sparse_ce_loss(self, y_true, y_pred):
        ce_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(
            labels=y_true,
            logits=y_pred)
        ce_loss = tf.reduce_sum(ce_loss) * (1. / self.global_batch_size)
        ce_loss /= tf.cast(tf.reduce_prod(tf.shape(y_true)[1:]), tf.float32)
        return ce_loss

    
    def tversky_loss(self, y_true, y_pred):
        # y_pred = tf.reshape(y_pred, (self.image_size[0] * self.image_size[1], self.num_classes))
        y_pred = tf.nn.softmax(y_pred)

        
        y_true_pos = Flatten()(y_true)
        y_pred_pos = Flatten()(y_pred)
        true_pos = tf.reduce_sum(y_true_pos * y_pred_pos)
        false_neg = tf.reduce_sum(y_true_pos * (1-y_pred_pos))
        false_pos = tf.reduce_sum((1-y_true_pos)*y_pred_pos)
        alpha = 0.7
        return (true_pos + self.tversky_smooth)/(true_pos + alpha*false_neg + (1-alpha)*false_pos + self.tversky_smooth)
    
    def focal_tversky_loss(self, y_true, y_pred):
        pt = self.tversky_loss(y_true=y_true, y_pred=y_pred)
        loss = tf.pow((1-pt), self.tversky_focal_gamma)
        return tf.reduce_sum(loss) * (1. / self.global_batch_size)
        


def bce_loss(y_true, y_pred, global_batch_size=16, use_multi_gpu=False):
    loss = losses.binary_crossentropy(y_true=y_true, y_pred=y_pred, from_logits=False)

    if use_multi_gpu:
        loss = tf.reduce_sum(loss) * (1. / global_batch_size)
        loss /= tf.cast(tf.reduce_prod(tf.shape(y_true)[1:]), tf.float32)
    else:
        loss = tf.reduce_mean(loss)

    return loss

def focal_bce_loss(y_true, y_pred):
    return tfa.losses.SigmoidFocalCrossEntropy()(y_true=y_true, y_pred=y_pred)


def distribute_ce_loss(y_true, y_pred):
    ce_loss = tf.keras.losses.SparseCategoricalCrossentropy(from_logits=True, reduction=tf.keras.losses.Reduction.NONE)(y_true=y_true, y_pred=y_pred)

    return ce_loss


def sparse_categorical_focal_loss(y_true, y_pred, gamma, *,
                                  class_weight: Optional[Any] = None,
                                  from_logits: bool = False, axis: int = -1,
                                  use_multi_gpu: bool = False,
                                  global_batch_size: int = 8,
                                  ) -> tf.Tensor:
    # Process focusing parameter
    gamma = tf.convert_to_tensor(gamma, dtype=tf.dtypes.float32)
    gamma_rank = gamma.shape.rank
    scalar_gamma = gamma_rank == 0

    # Process class weight
    if class_weight is not None:
        class_weight = tf.convert_to_tensor(class_weight,
                                            dtype=tf.dtypes.float32)

    # Process prediction tensor
    y_pred = tf.convert_to_tensor(y_pred)
    y_pred_rank = y_pred.shape.rank
    if y_pred_rank is not None:
        axis %= y_pred_rank
        if axis != y_pred_rank - 1:
            # Put channel axis last for sparse_softmax_cross_entropy_with_logits
            perm = list(itertools.chain(range(axis),
                                        range(axis + 1, y_pred_rank), [axis]))
            y_pred = tf.transpose(y_pred, perm=perm)
    elif axis != -1:
        raise ValueError(
            f'Cannot compute sparse categorical focal loss with axis={axis} on '
            'a prediction tensor with statically unknown rank.')
    y_pred_shape = tf.shape(y_pred)

    # Process ground truth tensor
    y_true = tf.dtypes.cast(y_true, dtype=tf.dtypes.int64)
    y_true_rank = y_true.shape.rank

    if y_true_rank is None:
        raise NotImplementedError('Sparse categorical focal loss not supported '
                                  'for target/label tensors of unknown rank')

    reshape_needed = (y_true_rank is not None and y_pred_rank is not None and
                      y_pred_rank != y_true_rank + 1)
    if reshape_needed:
        y_true = tf.reshape(y_true, [-1])
        y_pred = tf.reshape(y_pred, [-1, y_pred_shape[-1]])

    if from_logits:
        logits = y_pred
        probs = tf.nn.softmax(y_pred, axis=-1)
    else:
        probs = y_pred
        logits = tf.math.log(tf.clip_by_value(y_pred, _EPSILON, 1 - _EPSILON))

    

    xent_loss = tf.nn.sparse_softmax_cross_entropy_with_logits(
        labels=y_true,
        logits=logits)

    y_true_rank = y_true.shape.rank
    probs = tf.gather(probs, y_true, axis=-1, batch_dims=y_true_rank)
    if not scalar_gamma:
        gamma = tf.gather(gamma, y_true, axis=0, batch_dims=y_true_rank)
    focal_modulation = (1 - probs) ** gamma

    loss = focal_modulation * xent_loss

    if use_multi_gpu:
        loss = tf.reduce_sum(loss) * (1. / global_batch_size)
        loss /= tf.cast(tf.reduce_prod(tf.shape(y_true)[1:]), tf.float32)

    if class_weight is not None:
        class_weight = tf.gather(class_weight, y_true, axis=0,
                                 batch_dims=y_true_rank)
        loss *= class_weight

    if reshape_needed:
        loss = tf.reshape(loss, y_pred_shape[:-1])

    return loss

@tf.keras.utils.register_keras_serializable()
class SparseCategoricalFocalLoss(tf.keras.losses.Loss):
    def __init__(self, gamma, class_weight: Optional[Any] = None,
                 from_logits: bool = False, use_multi_gpu: bool = False,
                 global_batch_size: int = 16, num_classes: int = 16,
                  **kwargs):
        super().__init__(**kwargs)
        self.gamma = gamma
        self.class_weight = class_weight
        self.from_logits = from_logits
        self.use_multi_gpu = use_multi_gpu
        self.global_batch_size = global_batch_size
        self.num_classes = num_classes

    def get_config(self):
        config = super().get_config()
        config.update(gamma=self.gamma, class_weight=self.class_weight,
                      from_logits=self.from_logits)
        return config

    def call(self, y_true, y_pred):
        y_true = tf.cast(y_true, dtype=tf.float32)
        y_pred = tf.cast(y_pred, dtype=tf.float32)

        semantic_y_true = y_true[:, :, :, 0]
        semantic_y_pred = y_pred[:, :, :, :self.num_classes]

        print('semantic gt {0},  semantic pred {1}'.format(semantic_y_true, semantic_y_pred))

        confidence_y_true = y_true[:, :, :, 1]
        confidence_y_pred = y_pred[:, :, :, self.num_classes:][:, :, :, 0]

        print('semantic gt {0},  semantic pred {1}'.format(confidence_y_true, confidence_y_pred))

        confidence_loss = bce_loss(y_true=confidence_y_true, y_pred=confidence_y_pred,
                                   global_batch_size=self.global_batch_size, use_multi_gpu=self.use_multi_gpu)

        semantic_loss = sparse_categorical_focal_loss(y_true=semantic_y_true, y_pred=semantic_y_pred,
                                             class_weight=self.class_weight,
                                             gamma=self.gamma,
                                             from_logits=self.from_logits,
                                             use_multi_gpu=self.use_multi_gpu,
                                             global_batch_size=self.global_batch_size)

        return confidence_loss + semantic_loss

