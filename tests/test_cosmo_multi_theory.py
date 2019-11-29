import os
import numpy as np
from collections import OrderedDict
from cobaya.model import get_model
from cobaya.theory import Theory
from cobaya.tools import load_module
from cobaya.likelihood import LikelihoodInterface
from .common import process_modules_path


# Test separating out the BBN consistency constraint into separate theory code,
# using CAMB's BBN interpolator class. Tests dependencies/multi-theory with one
# agnostic theory

class BBN(Theory):
    bbn = None

    def get_requirements(self):
        return {'ombh2', 'nnu'}

    def calculate(self, state, want_derived=True, **params_values_dict):
        yhe = self.bbn.Y_He(self.provider.get_param('ombh2'),
                            self.provider.get_param('nnu') - 3.046)
        state['derived'] = {'YHe': yhe}

    def get_can_provide_params(self):
        return ['YHe']


class BBN2(Theory):
    params = {'ombh2': None, 'nnu': None, 'YHe': {'derived': True}}
    bbn = None

    def calculate(self, state, want_derived=True, **params_values_dict):
        if want_derived:
            state['derived'] = {'YHe': self.bbn.Y_He(params_values_dict['ombh2'],
                                                     params_values_dict['nnu'] - 3.046)}


def cmb_likelihood(_derived={'check'},
                   _theory={'Hubble': {'z': [0.5]}, 'CAMBdata': None}):
    results = _theory.get_CAMBdata()
    _derived['check'] = results.Params.YHe
    return results.Params.YHe


camb_params = {
    "ombh2": 0.022274,
    "omch2": 0.11913,
    "cosmomc_theta": 0.01040867,
    "As": 0.2132755716e-8,
    "ns": 0.96597,
    "tau": 0.0639,
    "nnu": 3.046}

bbn_table = "PRIMAT_Yp_DH_Error.dat"
debug = True
info = {'likelihood': {'cmb': cmb_likelihood},
        'theory': OrderedDict({
            'camb': {"extra_args": {"lens_potential_accuracy": 1},
                     "requires": ['YHe', 'ombh2'], "stop_at_error": True},
            'bbn': {'external': BBN, 'provides': ['YHe']}}),
        'params': camb_params,
        'debug': debug}

info2 = {'likelihood': {'cmb': {'external': cmb_likelihood}},
         'theory': OrderedDict({
             'camb': {"requires": ['YHe', 'ombh2']},
             'bbn': BBN2}),
         'params': camb_params, 'debug': debug}


def test_bbn_yhe(modules):
    modules = process_modules_path(modules)
    load_module("camb", path=os.path.join(modules, "code", "CAMB"))
    from camb.bbn import BBN_table_interpolator
    BBN.bbn = BBN_table_interpolator(bbn_table)
    BBN2.bbn = BBN.bbn

    info['params']['check'] = {'derived': True}

    for inf in (info, info2):
        inf['modules'] = modules
        for order in [1, -1]:
            for explicit_derived in [None, None, {'derived': True}]:
                print(inf, order, explicit_derived)
                model = get_model(inf)
                loglike, derived = model.loglikes({})
                vals = set([BBN.bbn.Y_He(camb_params['ombh2'])] + derived)
                assert len(vals) == 1, \
                    "wrong Yhe value: %s" % vals
                inf['params']["YHe"] = explicit_derived
            inf['params'].pop('YHe')
            inf['theory'] = OrderedDict(
                (p, v) for p, v in reversed(list(inf['theory'].items())))


# Not inherit from BBN to derive likelihoods that account for the theory error

class BBN_likelihood(BBN2, LikelihoodInterface):
    """
    Sample YHe and just calculate a direct theory likelihood
    """
    params = zip(['ombh2', 'nnu', 'YHe'], [None] * 3)

    def calculate(self, state, want_derived=True, **params_values_dict):
        ombh2 = params_values_dict['ombh2']
        delta_neff = params_values_dict['nnu'] - 3.046
        yhemean = self.bbn.Y_He(ombh2, delta_neff)
        error = self.bbn.get('sig(Yp^BBN)', ombh2, delta_neff)
        state['logp'] = -(params_values_dict['YHe'] - yhemean) ** 2 / (2 * error ** 2)

    def get_can_provide_params(self):
        return {}


class BBN_with_theory_errors(BBN, LikelihoodInterface):
    """
    The BBN theory prediction has an error. So we can derive a likelihood for
    sampling over a separate error parameter to account for it if we approximate
    the distribution as Gaussian.
    """
    params = {'BBN_delta': {'prior': {'min': 0, 'max': 1},
                            'ref': dict(dist='norm', loc=0, scale=1)}}

    def calculate(self, state, want_derived=True, **params_values_dict):
        ombh2, nnu = self.provider.get_param(['ombh2', 'nnu'])
        delta_neff = nnu - 3.046
        yhemean = self.bbn.Y_He(ombh2, delta_neff)
        # get theory error (neglecting difference between Y_He and Yp^BBN)
        error = self.bbn.get('sig(Yp^BBN)', ombh2, delta_neff)
        yhe = yhemean + error * params_values_dict['BBN_delta']
        if want_derived:
            state['derived'] = {'YHe': yhe}
        # take the error to be Gaussian
        state['logp'] = -params_values_dict['BBN_delta'] ** 2 / 2


info_error = {'likelihood': OrderedDict([('cmb', {'external': cmb_likelihood}),
                                         ('BBN', BBN_likelihood)]),
              'theory': OrderedDict({
                  'camb': {"requires": ['YHe', 'ombh2']}}),
              'params': dict(YHe={'prior': {'min': 0, 'max': 1}}, **camb_params),
              'debug': debug}

info_error2 = {'likelihood': OrderedDict([('cmb', {'external': cmb_likelihood}),
                                          ('BBN', {'external': BBN_with_theory_errors,
                                                   'provides': 'YHe'})]),
               'theory': OrderedDict({
                   'camb': {"requires": ['YHe', 'ombh2']}}),
               'params': dict(BBN_delta={'prior': {'min': -5, 'max': 5}}, **camb_params),
               'debug': debug}


def test_bbn_likelihood(modules):
    modules = process_modules_path(modules)
    load_module("camb", path=os.path.join(modules, "code", "CAMB"))
    from camb.bbn import BBN_table_interpolator
    BBN_likelihood.bbn = BBN_table_interpolator(bbn_table)
    info_error['modules'] = modules
    model = get_model(info_error)
    assert np.allclose(model.loglikes({'YHe': 0.246})[0], [0.246, -0.84340], rtol=1e-4), \
        "Failed BBN likelihood with %s" % info_error

    # second case, BBN likelihood has to be calculated before CAMB
    BBN_with_theory_errors.bbn = BBN_likelihood.bbn
    info_error2['modules'] = modules
    model = get_model(info_error2)
    assert np.allclose(model.loglikes({'BBN_delta': 1.0})[0], [0.24594834, -0.5],
                       rtol=1e-4)