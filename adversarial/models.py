# -*- coding: utf-8 -*-

"""Methods for constructing the neural networks used for the adversarial
training of de-correlated jet taggers.

Adapted from https://github.com/asogaard/AdversarialSubstructure/blob/master/models.py
"""

# Basic import(s)
import re
import numpy as np

# Keras import(s)
import keras
from keras import regularizers
from keras.models import Model
from keras.layers import Dense, Input, Dropout, Concatenate, Lambda
from keras.engine.topology import InputLayer
from keras.layers.normalization import BatchNormalization

# Project import(s)
from .layers import *
from .utils import snake_case

# Global variable definition(s)
RNG = np.random.RandomState(21)  # For reproducibility


# Utility methods for naming layers
def layer_name_factory (scope):
    """ ... """
    def layer_name (name):
        if scope:
            return '{}/{}'.format(scope, name)
        return name
    return layer_name


def keras_layer_name_factory (scope):
    """ ... """
    layer_name = layer_name_factory(scope)
    def keras_layer_name (cls):
        return layer_name('{}_{}'.format(snake_case(cls), K.get_uid(cls)))
    return keras_layer_name


def stack_layers (input_layer, architecture, default, scope=None):
    """Unified utility method to stack intermediate layers.

    This avoids code duplication between the classifier- and adversary model
    factory methods, and is based on the format in the configuration- and patch
    files, allowing for easy configuration of models e.g. for hyperparameter
    optimisation.

    Args:
        input_layer: The layer on which to stack batch normalisation-, dense-,
            and dropout regularisation layers.
        architecture: List of dictionaries, each one specifying the properties
            of a hidden, densely connected layer, optionally preceeded by a
            batch normalisation layer and succeeded by a dropout regularisation
            layer.
        default: Dictionary specifying the default configuration for all layers,
            optionally overwritten by each of the dicts in `architecture`.
        scope: Name of scope in which the layers should be created.

    Returns:
        The last Keras layer in the stack.
    """

    # Method(s) to get name of layers
    keras_layer_name = keras_layer_name_factory(scope)

    # Prepare first layer
    l = input_layer

    # Loop layer specifications
    for spec in architecture:

        # Update the specifications of the current layer to include any defaults
        opts = dict(**default)
        opts.update(spec)

        # Extract non-standard keyword arguments
        batchnorm = opts.pop('batchnorm', False)
        dropout   = opts.pop('dropout',   None)
        l1reg     = opts.pop('l1reg',     None)
        l2reg     = opts.pop('l2reg',     None)

        # 1: (Opt.) Add batch normalisation layer before dense layer
        if batchnorm:
            l = BatchNormalization(name=keras_layer_name('BatchNormalization'))(l)
            pass

        # 2: Add dense layer according to specifications
        l = Dense(name=keras_layer_name('Dense'),
                  activity_regularizer=regularizers.l1(l1reg) if l1reg else None,
                  kernel_regularizer  =regularizers.l2(l2reg) if l2reg else None,
                  **opts)(l)

        # 3: (Opt.) Add dropout regularisation layer after dense layer
        if dropout:
            l = Dropout(dropout, seed=RNG.randint(np.iinfo(np.int).max), name=keras_layer_name('Dropout'))(l)
            pass

        pass

    return l


def classifier_model (num_params, architecture=[], default=dict(), scope='classifier'):
    """Network model used for classifier/tagger.

    Args:
        num_params: Number of input features to the classifier.
        architecture: List of dicts specifying the architecture of the deep,
            sequential section of the adversary's network. See `stack_layers`.
        default: Default configuration of each layer in the deep, sequential
            section of the adversary's network. See `stack_layers`.
        scope: Name of scope in which the layers should be created.

    Returns:
        Keras model of the classifier network.
    """

    # Method(s) to get name of layers
    keras_layer_name = keras_layer_name_factory(scope)
    layer_name       = layer_name_factory(scope)

    # Input(s)
    classifier_input = Input(shape=(num_params,), name=layer_name('input'))

    # Layer(s)
    classifier_stack = stack_layers(classifier_input, architecture, default, scope=scope)

    # Output(s)
    classifier_output = Dense(1, activation='sigmoid', name=layer_name('output'))(classifier_stack)

    # Build model
    model = Model(inputs=classifier_input, outputs=classifier_output, name=scope)

    # Return
    return model


def adversary_model (gmm_dimensions, gmm_components=None, architecture=[], default=dict(), scope='adversary'):
    """Combined adversarial network model.

    This method creates an adversarial network model based on the provided
    `classifier`, taking as inputs the classifier input and the variables from
    which to de-correlation and outputting the classifer output as well as the
    posterior probability assigned to the input de-correlation variable
    configuration by the adversary's Gaussian mixture model (GMM) p.d.f.

    Args:
        gmm_dimensions: The number variables from which to de-correlated,
            corresponding to the number of dimensions in which the adversary's
            p.d.f. exists.
        gmm_components: The number of components in the adversary's GMM.
        architecture: List of dicts specifying the architecture of the deep,
            sequential section of the adversary's network. See `stack_layers`.
        default: Default configuration of each layer in the deep, sequential
            section of the adversary's network. See `stack_layers`.
        scope: Name of scope in which the layers should be created.

    Returns:
        Keras model of the combined adversarial network.
    """

    # Method(s) to get name of layers
    keras_layer_name = keras_layer_name_factory(scope)
    layer_name       = layer_name_factory(scope)

    # Input(s)
    adversary_input_clf = Input(shape=(1,),              name=layer_name('input_clf'))
    adversary_input_pt  = Input(shape=(1,),              name=layer_name('input_pt'))  # @TEMP
    adversary_input_par = Input(shape=(gmm_dimensions,), name=layer_name('input_par'))

    # Batch-normalise classifier output
    clf = adversary_input_clf  # BatchNormalization()(adversary_input_clf)

    # Re-scale input pt
    #pt = BatchNormalization()(adversary_input_pt)
    pt = Lambda(lambda pt: (pt - np.log(200.))/(np.log(2000.) - np.log(200.)))(adversary_input_pt)

    # Intermediate layer(s)
    inputs = Concatenate(name=layer_name('concatenate'))([clf, pt])
    features = stack_layers(inputs, architecture, default, scope=scope)

    # Posterior p.d.f. parameters
    r_coeffs = Dense(gmm_components, name=layer_name('coeffs'), activation='softmax')(features)
    r_means  = list()
    r_widths = list()
    for i in xrange(1, gmm_dimensions + 1):
        # Activation: Require all means to be in [0,1]
        r_means .append(Dense(gmm_components, activation='sigmoid',  name=layer_name('means_{}'.format(i)))(features) )
        pass
    for i in xrange(1, gmm_dimensions + 1):
        # Require all widths to be positive
        r_widths.append(Dense(gmm_components, activation='softplus', name=layer_name('widths_{}'.format(i)))(features) )
        pass

    # Posterior probability layer
    adversary_output = PosteriorLayer(gmm_components, gmm_dimensions, name=layer_name('output'))([r_coeffs] + r_means + r_widths + [adversary_input_par])

    # Build model
    model = Model(inputs=[adversary_input_clf, adversary_input_pt, adversary_input_par],
                  outputs=adversary_output,
                  name=scope)
    # Return
    return model


def combined_model (classifier, adversary, lambda_reg=None, lr_ratio=None, scope='combined'):
    """...

    Args:
        classifier: Keras model to be pitted against `adversary`. Assumed to be
            sequential N -> 1.
        adversary: Keras model to be pitted against `classifier`. Assumed to
            have two inputs, the first being the output from `classifier` and
            the second being the (kinematic) variables against which the de-
            correlation should be performed.
        lambda_reg: The regularisation parameter $\lambda$, controlling the
            weight on the adversary cost to the combined classifier and
            adversary objective function. This parameter controls the trade-off
            between powerful classification (`lambda_reg` low) and
            de-correlation (`lambda_reg` high).
        lr_ratio: The ratio of the classifiers's learning rate to the adversary's.
            This should be much smaller than 1, to let the adversary adapt more
            quickly than the classifier, to ensure stability of the final result.

    Returns:
        Keras model of the combined adversarial network.
    """

    # Method(s) to get name of layers
    keras_layer_name = keras_layer_name_factory(scope)
    layer_name       = layer_name_factory(scope)

    # Reconstruct classifier
    classifier_input = classifier.layers[0]

    combined_input_clf  = Input(shape=classifier_input.input_shape[1:], name=layer_name(classifier_input.name.replace('/', '_')))
    combined_output_clf = classifier(combined_input_clf)

    # Add gradient reversal layer
    gradient_reversal = GradientReversalLayer(lambda_reg * lr_ratio, name=keras_layer_name('GradientReversalLayer'))(combined_output_clf)

    # Reconstruct adversary
    input_layers   = filter(lambda l: type(l) == InputLayer, adversary.layers)
    adversary_input_pt  = filter(lambda l: l.name.endswith('_pt'),  input_layers)[0]
    adversary_input_par = filter(lambda l: l.name.endswith('_par'), input_layers)[0]
    
    inputs_adv = [
        Input(shape=adversary_input_pt .input_shape[1:], name=layer_name(adversary_input_pt .name.replace('/', '_'))),
        Input(shape=adversary_input_par.input_shape[1:], name=layer_name(adversary_input_par.name.replace('/', '_'))),
        ]
    outputs_adv = [adversary([gradient_reversal] + inputs_adv)]

    # Build model
    model = Model(inputs =[combined_input_clf]  + inputs_adv,
                  outputs=[combined_output_clf] + outputs_adv,
                  name=scope)

    # Return
    return model



def decorrelation_model (classifier, num_decorrelation_features, scope='decorrelation', **kwargs):
    """...

    Args:
        classifier: Keras model to be linearly decorrelated. Assumed to be
            sequential N -> 1.
        num_decorrelation_features: Number of fixed features from which the
            classifier should be decorrelated.

    Returns:
        Keras model of the combined decorrelation network.
    """

    # Method(s) to get name of layers
    keras_layer_name = keras_layer_name_factory(scope)
    layer_name       = layer_name_factory(scope)

    # Toggling sub-models
    classifier.trainable = True

    # Decorrelation inputs
    decorrelation_input   = Input(shape=(num_decorrelation_features,))
    decorrelation_weights = Input(shape=(1,))

    # Reconstruct classifier
    classifier_input  = Input(shape=classifier.layers[0].input_shape[1:])
    classifier_output = classifier(classifier_input)

    # Add decorrelation layer
    decorrelation_output = DecorrelationLayer()([classifier_output, decorrelation_input, decorrelation_weights])

    # Build model
    model = Model(inputs =[classifier_input,  decorrelation_input, decorrelation_weights],
                  outputs=[classifier_output, decorrelation_output],
                  name=scope)

    # Return
    return model
