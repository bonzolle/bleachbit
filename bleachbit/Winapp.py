# vim: ts=4:sw=4:expandtab

## BleachBit
## Copyright (C) 2011 Andrew Ziem
## http://bleachbit.sourceforge.net
##
## This program is free software: you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation, either version 3 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program.  If not, see <http://www.gnu.org/licenses/>.



"""
Import Winapp2.ini files
"""



import Cleaner
import Common
import ConfigParser
import os
import re
import sys
import traceback

from Action import ActionProvider, Delete, Winreg
from Common import _
from FileUtilities import listdir
from General import boolstr_to_bool, getText
from Windows import detect_registry_key
from platform import uname
from xml.dom.minidom import parseString

# TRANSLATORS: This is cleaner name for cleaners imported from winapp2.ini
langsecref_map = { '3021' : _('Applications'), \
# TRANSLATORS: This is cleaner name for cleaners imported from winapp2.ini
    '3022' : _('Internet'), \
# TRANSLATORS: This is cleaner name for cleaners imported from winapp2.ini
    '3023' : _('Multimedia'), \
# TRANSLATORS: This is cleaner name for cleaners imported from winapp2.ini
    '3024': _('Utilities'), \
# TRANSLATORS: This is cleaner name for cleaners imported from winapp2.ini.
    '3025' : _('Microsoft Windows'), \
    '3026' : _('Internet'), \
    '3027' : _('Internet'), \
    '3028' : _('Internet') }

def xml_escape(s):
    """Lightweight way to escape XML entities"""
    return s.replace('&', '&amp;').replace('"', '&quot;')


def section2option(s):
    """Normalize section name to appropriate option name"""
    ret = re.sub(r'[^a-z0-9]', '_', s.lower())
    ret = re.sub(r'_+', '_', ret)
    ret = re.sub(r'(^_|_$)', '', ret)
    return ret

def preexpand(s):
    """Prepare pathname for expansion by changing %foo% to ${foo}"""
    return re.sub(r'%([a-zA-Z]+)%', r'${\1}', s)


class Winapp:
    """Create cleaners from a Winapp2.ini-style file"""

    def __init__(self, pathname):
        """Create cleaners from a Winapp2.ini-style file"""

        self.cleaners = {}
        for langsecref in set(langsecref_map.values()):
            lid = langsecref.lower().replace(' ','_')
            self.cleaners[lid] = Cleaner.Cleaner()
            self.cleaners[lid].id = lid
            self.cleaners[lid].name = langsecref
            self.cleaners[lid].description = _('Imported from winapp2.ini')
        self.errors = 0
        self.parser = ConfigParser.RawConfigParser()
        self.parser.read(pathname)
        for section in self.parser.sections():
            try:
                self.handle_section(section)
            except:
                self.errors += 1
                print 'ERROR: parsing error in section %s' % section
                traceback.print_exc()


    def handle_section(self, section):
        """Parse a section"""
        if self.parser.has_option(section, 'detect'):
            key = self.parser.get(section, 'detect')
            if not detect_registry_key(key):
                return
        if self.parser.has_option(section, 'detectfile'):
            pathname = os.path.expandvars(preexpand(self.parser.get(section, 'detectfile')))
            if not os.path.exists(pathname):
                return
        if self.parser.has_option(section, 'detectos'):
            min_os = self.parser.get(section, 'detectos')
            cur_os = uname()[3][0:3]
            if min_os > cur_os:
                return
        if self.parser.has_option(section, 'excludekey'):
            print 'ERROR: ExcludeKey not implemented, section=', section
            return
        lid = langsecref_map[self.parser.get(section, 'langsecref')].lower().replace(' ','_')
        self.cleaners[lid].add_option(section2option(section), section.replace('*', ''), '')
        for option in self.parser.options(section):
            if option.startswith('filekey'):
                self.handle_filekey(lid, section, option)
            elif option.startswith('regkey'):
                self.handle_regkey(lid, section, option)
            elif option == 'warning':
                self.cleaner[lid].set_warning(section2option(section), self.parser.get(section, 'warning'))
            elif option in ('default', 'detectfile', 'detect', 'langsecref'):
                pass
            else:
                print 'WARNING: unknown option', option


    def __make_file_provider(self, dirname, filename, recurse, removeself):
        """Change parsed FileKey to action provider"""
        regex = ''
        if recurse:
            search = 'walk.files'
            path = dirname
            if filename.startswith('*.'):
                filename = filename.replace('*.', '.')
            if '.*' == filename:
                if removeself:
                    search = 'walk.all'
            else:
                regex = ' regex="%s" ' % (re.escape(filename) + '$')
        else:
            search = 'glob'
            path = os.path.join(dirname, filename)
            if -1 == path.find('*'):
                search = 'file'
        action_str = '<option command="delete" search="%s" path="%s" %s/>' % \
            (search, xml_escape(path), regex)
        print 'debug:', action_str
        yield Delete(parseString(action_str).childNodes[0])
        if removeself:
            action_str = '<option command="delete" search="file" path="%s"/>' % xml_escape(dirname)
            print 'debug:', action_str
            yield Delete(parseString(action_str).childNodes[0])


    def handle_filekey(self, lid, ini_section, ini_option):
        """Parse a FileKey# option.

        Section is [Application Name] and option is the FileKey#"""
        elements = self.parser.get(ini_section, ini_option).strip().split('|')
        dirname = preexpand(elements.pop(0))
        filename = ""
        if elements:
            filename = elements.pop(0)
        recurse = False
        removeself = False
        for element in elements:
            if 'RECURSE' == element:
                recurse = True
            elif 'REMOVESELF' == element:
                recurse = True
                removeself = True
            else:
                print 'WARNING: unknown file option', element
        print 'debug:', self.parser.get(ini_section, ini_option)
        for provider in self.__make_file_provider(dirname, filename, recurse, removeself):
            self.cleaners[lid].add_action(section2option(ini_section), provider)


    def handle_regkey(self, lid, ini_section, ini_option):
        """Parse a RegKey# option"""
        elements = self.parser.get(ini_section, ini_option).strip().split('|')
        path = elements[0]
        name = ""
        if 2 == len(elements):
            name = 'name="%s"' % xml_escape(elements[1])
        action_str = '<option command="winreg" path="%s" %s/>' % (path, name)
        provider = Winreg(parseString(action_str).childNodes[0])
        self.cleaners[lid].add_action(section2option(ini_section), provider)


    def get_cleaners(self):
        """Return the created cleaners"""
        for langsecref in set(langsecref_map.values()):
            lid = langsecref.lower().replace(' ','_')
            if self.cleaners[lid].is_usable():
                yield self.cleaners[lid]


def list_winapp_files():
    """List winapp2.ini files"""
    fn = os.path.join(Common.personal_cleaners_dir, 'winapp2.ini')
    if os.path.exists(fn):
        yield fn


def load_cleaners():
    """Scan for winapp2.ini files and load them"""
    for pathname in list_winapp_files():
        try:
            inicleaner = Winapp(pathname)
        except:
            print "Error reading winapp2.ini cleaner '%s'" % pathname
            traceback.print_exc()
        else:
            import pdb; pdb.set_trace()
            for cleaner in inicleaner.get_cleaners():
                Cleaner.backends[cleaner.id] = cleaner
