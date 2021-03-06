# -*- coding: utf-8 -*-
'''
    unit.loader
    ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

    Test Salt's loader
'''

# Import Python libs
from __future__ import absolute_import
import inspect
import tempfile
import shutil
import os

# Import Salt Testing libs
from salttesting import TestCase
from salttesting.helpers import ensure_in_syspath

ensure_in_syspath('../../')

import integration

# Import Salt libs
# pylint: disable=import-error,no-name-in-module,redefined-builtin
import salt.ext.six as six
from salt.ext.six.moves import range
from salt.config import minion_config
# pylint: enable=no-name-in-module,redefined-builtin

from salt.loader import LazyLoader, _module_dirs


class LazyLoaderVirtualEnabledTest(TestCase):
    '''
    Test the base loader of salt.
    '''
    def setUp(self):
        self.opts = _config = minion_config(None)
        self.loader = LazyLoader(_module_dirs(self.opts, 'modules', 'module'),
                                 self.opts,
                                 tag='modules')

    def test_basic(self):
        '''
        Ensure that it only loads stuff when needed
        '''
        # make sure it starts empty
        self.assertEqual(self.loader._dict, {})
        # get something, and make sure its a func
        self.assertTrue(inspect.isfunction(self.loader['test.ping']))

        # make sure we only loaded "test" functions
        for key, val in six.iteritems(self.loader._dict):
            self.assertEqual(key.split('.', 1)[0], 'test')

        # make sure the depends thing worked (double check of the depends testing,
        # since the loader does the calling magically
        self.assertFalse('test.missing_func' in self.loader._dict)

    def test_len_load(self):
        '''
        Since LazyLoader is a MutableMapping, if someone asks for len() we have
        to load all
        '''
        self.assertEqual(self.loader._dict, {})
        len(self.loader)  # force a load all
        self.assertNotEqual(self.loader._dict, {})

    def test_iter_load(self):
        '''
        Since LazyLoader is a MutableMapping, if someone asks to iterate we have
        to load all
        '''
        self.assertEqual(self.loader._dict, {})
        # force a load all
        for key, func in six.iteritems(self.loader):
            break
        self.assertNotEqual(self.loader._dict, {})

    def test_context(self):
        '''
        Make sure context is shared across modules
        '''
        # make sure it starts empty
        self.assertEqual(self.loader._dict, {})
        # get something, and make sure its a func
        func = self.loader['test.ping']
        func.__globals__['__context__']['foo'] = 'bar'
        self.assertEqual(self.loader['test.echo'].__globals__['__context__']['foo'], 'bar')
        self.assertEqual(self.loader['grains.get'].__globals__['__context__']['foo'], 'bar')

    def test_globals(self):
        func_globals = self.loader['test.ping'].__globals__
        self.assertEqual(func_globals['__grains__'], self.opts.get('grains', {}))
        self.assertEqual(func_globals['__pillar__'], self.opts.get('pillar', {}))
        # the opts passed into modules is at least a subset of the whole opts
        for key, val in six.iteritems(func_globals['__opts__']):
            self.assertEqual(self.opts[key], val)

    def test_pack(self):
        self.loader.pack['__foo__'] = 'bar'
        func_globals = self.loader['test.ping'].__globals__
        self.assertEqual(func_globals['__foo__'], 'bar')

    def test_virtual(self):
        self.assertNotIn('test_virtual.ping', self.loader)


class LazyLoaderVirtualDisabledTest(TestCase):
    '''
    Test the loader of salt without __virtual__
    '''
    def setUp(self):
        self.opts = _config = minion_config(None)
        self.loader = LazyLoader(_module_dirs(self.opts, 'modules', 'module'),
                                 self.opts,
                                 tag='modules',
                                 virtual_enable=False)

    def test_virtual(self):
        self.assertTrue(inspect.isfunction(self.loader['test_virtual.ping']))


class LazyLoaderWhitelistTest(TestCase):
    '''
    Test the loader of salt with a whitelist
    '''
    def setUp(self):
        self.opts = _config = minion_config(None)
        self.loader = LazyLoader(_module_dirs(self.opts, 'modules', 'module'),
                                 self.opts,
                                 tag='modules',
                                 whitelist=['test', 'pillar'])

    def test_whitelist(self):
        self.assertTrue(inspect.isfunction(self.loader['test.ping']))
        self.assertTrue(inspect.isfunction(self.loader['pillar.get']))

        self.assertNotIn('grains.get', self.loader)


module_template = '''
__load__ = ['test', 'test_alias']
__func_alias__ = dict(test_alias='working_alias')
from salt.utils.decorators import depends

def test():
    return {count}

def test_alias():
    return True

def test2():
    return True

@depends('non_existantmodulename')
def test3():
    return True

@depends('non_existantmodulename', fallback_function=test)
def test4():
    return True
'''


class LazyLoaderReloadingTest(TestCase):
    '''
    Test the loader of salt with changing modules
    '''
    module_name = 'loadertest'
    module_key = 'loadertest.test'

    def setUp(self):
        self.opts = _config = minion_config(None)
        self.tmp_dir = tempfile.mkdtemp(dir=integration.TMP)

        self.count = 0

        dirs = _module_dirs(self.opts, 'modules', 'module')
        dirs.append(self.tmp_dir)
        self.loader = LazyLoader(dirs,
                                 self.opts,
                                 tag='modules')

    def tearDown(self):
        shutil.rmtree(self.tmp_dir)

    def update_module(self):
        self.count += 1
        with open(self.module_path, 'wb') as fh:
            fh.write(module_template.format(count=self.count))
            fh.flush()
            os.fsync(fh.fileno())  # flush to disk

        # pyc files don't like it when we change the original quickly
        # since the header bytes only contain the timestamp (granularity of seconds)
        # TODO: don't write them? Is *much* slower on re-load (~3x)
        # https://docs.python.org/2/library/sys.html#sys.dont_write_bytecode
        try:
            os.unlink(self.module_path + 'c')
        except OSError:
            pass

    def rm_module(self):
        os.unlink(self.module_path)
        os.unlink(self.module_path + 'c')

    @property
    def module_path(self):
        return os.path.join(self.tmp_dir, '{0}.py'.format(self.module_name))

    def test_alias(self):
        '''
        Make sure that you can access alias-d modules
        '''
        # ensure it doesn't exist
        self.assertNotIn(self.module_key, self.loader)

        self.update_module()
        self.assertNotIn('{0}.test_alias'.format(self.module_name), self.loader)
        self.assertTrue(inspect.isfunction(self.loader['{0}.working_alias'.format(self.module_name)]))

    def test_clear(self):
        self.assertTrue(inspect.isfunction(self.loader['test.ping']))
        self.update_module()  # write out out custom module
        self.loader.clear()  # clear the loader dict

        # force a load of our module
        self.assertTrue(inspect.isfunction(self.loader[self.module_key]))

        # make sure we only loaded our custom module
        # which means that we did correctly refresh the file mapping
        for k, v in six.iteritems(self.loader._dict):
            self.assertTrue(k.startswith(self.module_name))

    def test_load(self):
        # ensure it doesn't exist
        self.assertNotIn(self.module_key, self.loader)

        self.update_module()
        self.assertTrue(inspect.isfunction(self.loader[self.module_key]))

    def test__load__(self):
        '''
        If a module specifies __load__ we should only load/expose those modules
        '''
        self.update_module()

        # ensure it doesn't exist
        self.assertNotIn(self.module_key + '2', self.loader)

    def test__load__and_depends(self):
        '''
        If a module specifies __load__ we should only load/expose those modules
        '''
        self.update_module()
        # ensure it doesn't exist
        self.assertNotIn(self.module_key + '3', self.loader)
        self.assertNotIn(self.module_key + '4', self.loader)

    def test_reload(self):
        # ensure it doesn't exist
        self.assertNotIn(self.module_key, self.loader)

        # make sure it updates correctly
        for x in range(1, 3):
            self.update_module()
            self.loader.clear()
            self.assertEqual(self.loader[self.module_key](), self.count)

        self.rm_module()
        # make sure that even if we remove the module, its still loaded until a clear
        self.assertEqual(self.loader[self.module_key](), self.count)
        self.loader.clear()
        self.assertNotIn(self.module_key, self.loader)
