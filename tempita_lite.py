# -*- coding: utf-8 -*-
"""
A small templating language

This implements a small templating language.  This language implements
if/elif/else, for/continue/break, expressions.
The syntax is::

  {{any expression (function calls etc)}}
  {{any expression | filter}}
  {{for x in y}}...{{endfor}}
  {{if x}}x{{elif y}}y{{else}}z{{endif}}
  {{default var = default_value}}
  {{inherit ...}}
  {{def block}}
  {{# comment}}

You use this with the ``Template`` class or the ``sub`` shortcut.
The ``Template`` class takes the template string and the name of
the template (for errors) and a default namespace.  Then (like
``string.Template``) you can call the ``tmpl.substitute(**kw)``
method to make a substitution (or ``tmpl.substitute(a_dict)``).

``sub(content, **kw)`` substitutes the template immediately.  You
can use ``__name='tmpl.html'`` to set the name of the template.

If there are syntax errors ``TemplateError`` will be raised.

Copyright (c) 2015 Wolfgang Langner
License MIT, see license.txt.
"""

import re
import sys
import cgi
import os
import tokenize
import inspect
from copy import copy
from pprint import pprint

__all__ = ['TemplateError', 'Template', 'sub', 'HTMLTemplate',
           'sub_html', 'html', 'looper']

__version__ = "0.6.0dev"

in_re = re.compile(r'\s+in\s+')
var_re = re.compile(r'^[a-z_][a-z0-9_]*$', re.I)

#
# Python 2, 3 compatibility stuff
#

PY2 = True if sys.version_info[0] == 2 else False

if PY2:
    basestring_ = basestring
else:
    basestring_ = (bytes, str)
    unicode = str


def coerce_text(v):
    if not isinstance(v, basestring_):
        if PY2:
            attr = '__unicode__'
        else:
            attr = '__str__'
        if hasattr(v, attr):
            return unicode(v)
        else:
            return bytes(v)
    return v

#
# begin _looper.py
#

class looper(object):
    """
    Helper for looping (particularly in templates)

    Use this like::

        for loop, item in looper(seq):
            if loop.first:
                ...
    """

    def __init__(self, seq):
        self.seq = seq

    def __iter__(self):
        return looper_iter(self.seq)

    def __repr__(self):
        return '<%s for %r>' % (
            self.__class__.__name__, self.seq)


class looper_iter(object):

    def __init__(self, seq):
        self.seq = list(seq)
        self.pos = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self.pos >= len(self.seq):
            raise StopIteration
        result = loop_pos(self.seq, self.pos), self.seq[self.pos]
        self.pos += 1
        return result

    if PY2:
        next = __next__


class loop_pos(object):

    def __init__(self, seq, pos):
        self.seq = seq
        self.pos = pos

    def __repr__(self):
        return '<loop pos=%r at %r>' % (
            self.seq[self.pos], self.pos)

    def index(self):
        return self.pos
    index = property(index)

    def number(self):
        return self.pos + 1
    number = property(number)

    def item(self):
        return self.seq[self.pos]
    item = property(item)

    def __next__(self):
        try:
            return self.seq[self.pos + 1]
        except IndexError:
            return None
    __next__ = property(__next__)

    if PY2:
        next = __next__

    def previous(self):
        if self.pos == 0:
            return None
        return self.seq[self.pos - 1]
    previous = property(previous)

    def odd(self):
        return not self.pos % 2
    odd = property(odd)

    def even(self):
        return self.pos % 2
    even = property(even)

    def first(self):
        return self.pos == 0
    first = property(first)

    def last(self):
        return self.pos == len(self.seq) - 1
    last = property(last)

    def length(self):
        return len(self.seq)
    length = property(length)

    def first_group(self, getter=None):
        """
        Returns true if this item is the start of a new group,
        where groups mean that some attribute has changed.  The getter
        can be None (the item itself changes), an attribute name like
        ``'.attr'``, a function, or a dict key or list index.
        """
        if self.first:
            return True
        return self._compare_group(self.item, self.previous, getter)

    def last_group(self, getter=None):
        """
        Returns true if this item is the end of a new group,
        where groups mean that some attribute has changed.  The getter
        can be None (the item itself changes), an attribute name like
        ``'.attr'``, a function, or a dict key or list index.
        """
        if self.last:
            return True
        return self._compare_group(self.item, self.__next__, getter)

    def _compare_group(self, item, other, getter):
        if getter is None:
            return item != other
        elif (isinstance(getter, basestring_)
              and getter.startswith('.')):
            getter = getter[1:]
            if getter.endswith('()'):
                getter = getter[:-2]
                return getattr(item, getter)() != getattr(other, getter)()
            else:
                return getattr(item, getter) != getattr(other, getter)
        elif hasattr(getter, '__call__'):
            return getter(item) != getter(other)
        else:
            return item[getter] != other[getter]

#
# end _looper.py
#

class TemplateError(Exception):
    """Exception raised while parsing a template
    """

    def __init__(self, message, position, name=None):
        Exception.__init__(self, message)
        self.position = position
        self.name = name

    def __str__(self):
        msg = ' '.join(self.args)
        if self.position:
            msg = '%s at line %s column %s' % (
                msg, self.position[0], self.position[1])
        if self.name:
            msg += ' in %s' % self.name
        return msg


class _TemplateContinue(Exception):
    pass


class _TemplateBreak(Exception):
    pass


def get_file_template(name, from_template):
    path = os.path.join(os.path.dirname(from_template.name), name)
    return from_template.__class__.from_filename(
        path, namespace=from_template.namespace,
        get_template=from_template.get_template)


class Template(object):
    """
    Basic tempita template class.

    Initialize with template content and use substitute to get the result.

    :param str content: The template content as sting.
    :param str name: Optional name of template.
    :param dict namespace: Namespace used to get variables and functions.
    :param stacklevel int: Stacklevel used to find the name and other
                           information for error output.
    :param function get_template: A function used to find the parent template
                                  if inherit is used.
    :param default_inherit: Default inheritance function.
    :param int line_offset: If the template is embedded and does not start with
                        line 1 a line offset can be specified.
    :param tuple delimiters: A tuple of the delimiters used in template content.
    :return: A new template object.
    """

    default_namespace = {
        'start_braces': '{{',
        'end_braces': '}}',
        'looper': looper,
    }

    default_encoding = 'utf8'
    default_inherit = None
    default_filter = None

    def __init__(self, content, name=None, namespace=None, stacklevel=None,
                 get_template=None, default_inherit=None, line_offset=0,
                 delimeters=None):
        self.content = content

        # set delimeters
        if delimeters is None:
            delimeters = (self.default_namespace['start_braces'],
                          self.default_namespace['end_braces'])
        else:
            assert len(delimeters) == 2 and all(
                [isinstance(delimeter, basestring_)
                    for delimeter in delimeters])
            self.default_namespace = self.__class__.default_namespace.copy()
            self.default_namespace['start_braces'] = delimeters[0]
            self.default_namespace['end_braces'] = delimeters[1]
        self.delimeters = delimeters

        #self._unicode = is_unicode(content)
        self._unicode = isinstance(content, unicode)
        if name is None and stacklevel is not None:
            try:
                caller = sys._getframe(stacklevel)
            except ValueError:
                pass
            else:
                globals = caller.f_globals
                lineno = caller.f_lineno
                if '__file__' in globals:
                    name = globals['__file__']
                    if name.endswith('.pyc') or name.endswith('.pyo'):
                        name = name[:-1]
                elif '__name__' in globals:
                    name = globals['__name__']
                else:
                    name = '<string>'
                if lineno:
                    name += ':%s' % lineno
        self.name = name
        self._parsed = parse(
            content, name=name, line_offset=line_offset,
            delimeters=self.delimeters)
        if namespace is None:
            namespace = {}
        self.namespace = namespace
        self.get_template = get_template
        if default_inherit is not None:
            self.default_inherit = default_inherit

    @classmethod
    def from_filename(cls, filename, namespace=None, encoding=None,
                      default_inherit=None, get_template=get_file_template):
        with open(filename, 'rb') as f:
            c = f.read()
        if encoding:
            c = c.decode(encoding)
        return cls(content=c, name=filename, namespace=namespace,
                   default_inherit=default_inherit, get_template=get_template)

    def __repr__(self):
        return '<%s %s name=%r>' % (
            self.__class__.__name__,
            hex(id(self))[2:], self.name)

    def substitute(self, *args, **kw):
        """
        Substitue the temlate with the specified arguments.
        If one positional argument is given this is interpreted as a dict.
        """
        if args:
            if kw:
                raise TypeError(
                    "You can only give positional *or* keyword arguments")
            if len(args) > 1:
                raise TypeError(
                    "You can only give one positional argument")
            if not hasattr(args[0], 'items'):
                raise TypeError(
                    ("If you pass in a single argument, you must pass in a ",
                     "dict-like object (with a .items() method); you gave %r")
                    % (args[0],))
            kw = args[0]
        ns = copy(kw)
        ns['__template_name__'] = self.name
        if self.namespace:
            ns.update(self.namespace)
        result, defs, inherit = self._interpret(ns)
        if not inherit:
            inherit = self.default_inherit
        if inherit:
            result = self._interpret_inherit(result, defs, inherit, ns)
        return result

    def _interpret(self, ns):
        # __traceback_hide__ = True
        parts = []
        defs = {}
        self._interpret_codes(self._parsed, ns, out=parts, defs=defs)
        if '__inherit__' in defs:
            inherit = defs.pop('__inherit__')
        else:
            inherit = None
        return ''.join(parts), defs, inherit

    def _interpret_inherit(self, body, defs, inherit_template, ns):
        # __traceback_hide__ = True
        if not self.get_template:
            raise TemplateError(
                'You cannot use inheritance without passing in get_template',
                position=None, name=self.name)
        templ = self.get_template(inherit_template, self)
        self_ = TemplateObject(self.name)
        for name, value in defs.items():
            setattr(self_, name, value)
        self_.body = body
        ns = ns.copy()
        ns['self'] = self_
        return templ.substitute(ns)

    def _interpret_codes(self, codes, ns, out, defs):
        # __traceback_hide__ = True
        for item in codes:
            if isinstance(item, basestring_):
                out.append(item)
            else:
                self._interpret_code(item, ns, out, defs)

    def _interpret_code(self, code, ns, out, defs):
        # __traceback_hide__ = True
        name, pos = code[0], code[1]
        if name == 'continue':
            raise _TemplateContinue()
        elif name == 'break':
            raise _TemplateBreak()
        elif name == 'for':
            vars, expr, content = code[2], code[3], code[4]
            expr = self._eval(expr, ns, pos)
            self._interpret_for(vars, expr, content, ns, out, defs)
        elif name == 'cond':
            parts = code[2:]
            self._interpret_if(parts, ns, out, defs)
        elif name == 'expr':
            parts = code[2].split('|')
            base = self._eval(parts[0], ns, pos)
            if len(parts) == 1 and self.default_filter:
                base = self.default_filter(base)
            for part in parts[1:]:
                func = self._eval(part, ns, pos)
                base = func(base)
            out.append(self._repr(base, pos))
        elif name == 'default':
            var, expr = code[2], code[3]
            if var not in ns:
                result = self._eval(expr, ns, pos)
                ns[var] = result
        elif name == 'inherit':
            expr = code[2]
            value = self._eval(expr, ns, pos)
            defs['__inherit__'] = value
        elif name == 'def':
            name = code[2]
            #signature = code[3]
            parts = code[4]
            ns[name] = defs[name] = TemplateDef(
                self, name, body=parts, ns=ns, pos=pos)
        elif name == 'comment':
            return
        else:
            assert 0, "Unknown code: %r" % name

    def _interpret_for(self, vars, expr, content, ns, out, defs):
        # __traceback_hide__ = True
        for item in expr:
            if len(vars) == 1:
                ns[vars[0]] = item
            else:
                if len(vars) != len(item):
                    raise ValueError(
                        'Need %i items to unpack (got %i items)'
                        % (len(vars), len(item)))
                for name, value in zip(vars, item):
                    ns[name] = value
            try:
                self._interpret_codes(content, ns, out, defs)
            except _TemplateContinue:
                continue
            except _TemplateBreak:
                break

    def _interpret_if(self, parts, ns, out, defs):
        # __traceback_hide__ = True
        # @@: if/else/else gets through
        for part in parts:
            assert not isinstance(part, basestring_)
            name, pos = part[0], part[1]
            if name == 'else':
                result = True
            else:
                result = self._eval(part[2], ns, pos)
            if result:
                self._interpret_codes(part[3], ns, out, defs)
                break

    def _eval(self, code, ns, pos):
        # __traceback_hide__ = True
        try:
            try:
                value = eval(code, self.default_namespace, ns)
            except SyntaxError as e:
                raise SyntaxError(
                    'invalid syntax in expression: %s' % code)
            return value
        except:
            exc_info = sys.exc_info()
            e = exc_info[1]
            if getattr(e, 'args', None):
                arg0 = e.args[0]
            else:
                arg0 = coerce_text(e)
            e.args = (self._add_line_info(arg0, pos),)
            #raise (exc_info[1], e, exc_info[2])
            raise

    def _repr(self, value, pos):
        # __traceback_hide__ = True
        try:
            if value is None:
                return ''
            if self._unicode:
                try:
                    value = unicode(value)
                except UnicodeDecodeError:
                    value = bytes(value)
            else:
                if not isinstance(value, basestring_):
                    value = coerce_text(value)
                if (isinstance(value, unicode) and self.default_encoding):
                    value = value.encode(self.default_encoding)
        except:
            exc_info = sys.exc_info()
            e = exc_info[1]
            e.args = (self._add_line_info(e.args[0], pos),)
            #raise(exc_info[1], e, exc_info[2])
            raise
        else:
            if self._unicode and isinstance(value, bytes):
                if not self.default_encoding:
                    raise UnicodeDecodeError(
                        'Cannot decode bytes value %r into unicode '
                        '(no default_encoding provided)' % value)
                try:
                    value = value.decode(self.default_encoding)
                except UnicodeDecodeError as e:
                    raise UnicodeDecodeError(
                        e.encoding,
                        e.object,
                        e.start,
                        e.end,
                        e.reason + ' in string %r' % value)
            elif not self._unicode and isinstance(value, unicode):
                if not self.default_encoding:
                    raise UnicodeEncodeError(
                        'Cannot encode unicode value %r into bytes '
                        '(no default_encoding provided)' % value)
                value = value.encode(self.default_encoding)
            return value

    def _add_line_info(self, msg, pos):
        msg = "%s at line %s column %s" % (
            msg, pos[0], pos[1])
        if self.name:
            msg += " in file %s" % self.name
        return msg


def sub(content, delimeters=None, **kw):
    """
    Create a Template and substitute it with provided parameters.
    Handy function to do all in one step.
    If no keyword parameters are given the local context
    of the caller is used.
    """
    if not kw:
        frame = inspect.currentframe()
        try:
            kw = frame.f_back.f_locals
        finally:
            del frame
    print(kw)
    name = kw.get('__name')
    tmpl = Template(content, name=name, delimeters=delimeters)
    return tmpl.substitute(kw)


############################################################
## HTML Templating
############################################################


class html(object):

    def __init__(self, value):
        self.value = value

    def __str__(self):
        return self.value

    def __html__(self):
        return self.value

    def __repr__(self):
        return '<%s %r>' % (
            self.__class__.__name__, self.value)


def html_quote(value, force=True):
    if not force and hasattr(value, '__html__'):
        return value.__html__()
    if value is None:
        return ''
    if not isinstance(value, basestring_):
        value = coerce_text(value)
    if not PY2 and isinstance(value, bytes):
        value = cgi.escape(value.decode('latin1'), 1)
        value = value.encode('latin1')
    else:
        value = cgi.escape(value, 1)
    if PY2:
        if isinstance(value, unicode):
            value = value.encode('ascii', 'xmlcharrefreplace')
    return value


def url(v):
    if PY2:
        from urllib import quote
    else:
        from urllib.parse import quote
    v = coerce_text(v)
    if isinstance(v, unicode):
        v = v.encode('utf8')
    return quote(v)


def attr(**kw):
    kw = list(kw.items())
    kw.sort()
    parts = []
    for name, value in kw:
        if value is None:
            continue
        if name.endswith('_'):
            name = name[:-1]
        parts.append('%s="%s"' % (html_quote(name), html_quote(value)))
    return html(' '.join(parts))


class HTMLTemplate(Template):

    default_namespace = Template.default_namespace.copy()
    default_namespace.update(dict(
        html=html,
        attr=attr,
        url=url,
        html_quote=html_quote))

    def _repr(self, value, pos):
        if hasattr(value, '__html__'):
            value = value.__html__()
            quote = False
        else:
            quote = True
        plain = Template._repr(self, value, pos)
        if quote:
            return html_quote(plain)
        else:
            return plain


def sub_html(content, **kw):
    name = kw.get('__name')
    tmpl = HTMLTemplate(content, name=name)
    return tmpl.substitute(kw)


class TemplateDef(object):
    def __init__(self, template, func_name,
                 body, ns, pos, bound_self=None):
        self._template = template
        self._func_name = func_name
        self._body = body
        self._ns = ns
        self._pos = pos
        self._bound_self = bound_self

    def __repr__(self):
        return '<tempita function %s at %s:%s>' % (
            self._func_name, self._template.name, self._pos)

    def __str__(self):
        return self()

    def __call__(self, *args, **kw):
        ns = self._ns.copy()
        #ns.update(values)
        if self._bound_self is not None:
            ns['self'] = self._bound_self
        out = []
        subdefs = {}
        self._template._interpret_codes(self._body, ns, out, subdefs)
        return ''.join(out)

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return self.__class__(
            self._template, self._func_name,
            self._body, self._ns, self._pos, bound_self=obj)


class TemplateObject(object):

    def __init__(self, name):
        self.__name = name
        self.get = TemplateObjectGetter(self)

    def __repr__(self):
        return '<%s %s>' % (self.__class__.__name__, self.__name)


class TemplateObjectGetter(object):

    def __init__(self, template_obj):
        self.__template_obj = template_obj

    def __getattr__(self, attr):
        return getattr(self.__template_obj, attr, Empty)

    def __repr__(self):
        return '<%s around %r>' % (
            self.__class__.__name__, self.__template_obj)


class _Empty(object):
    def __call__(self, *args, **kw):
        return self

    def __str__(self):
        return ''

    def __repr__(self):
        return 'Empty'

    def __unicode__(self):
        return u''

    def __iter__(self):
        return iter(())

    def __bool__(self):
        return False

    if PY2:
        __nonzero__ = __bool__

Empty = _Empty()
del _Empty

############################################################
## Lexing and Parsing
############################################################


def lex(s, name=None, trim_whitespace=True, line_offset=0, delimeters=None):
    if delimeters is None:
        delimeters = (Template.default_namespace['start_braces'],
                      Template.default_namespace['end_braces'])
    in_expr = False
    chunks = []
    last = 0
    last_pos = (line_offset + 1, 1)
    token_re = re.compile(r'%s|%s' % (re.escape(delimeters[0]),
                                      re.escape(delimeters[1])))
    for match in token_re.finditer(s):
        expr = match.group(0)
        pos = find_position(s, match.end(), last, last_pos)
        if expr == delimeters[0] and in_expr:
            raise TemplateError('%s inside expression' % delimeters[0],
                                position=pos,
                                name=name)
        elif expr == delimeters[1] and not in_expr:
            raise TemplateError('%s outside expression' % delimeters[1],
                                position=pos,
                                name=name)
        if expr == delimeters[0]:
            part = s[last:match.start()]
            if part:
                chunks.append(part)
            in_expr = True
        else:
            chunks.append((s[last:match.start()], last_pos))
            in_expr = False
        last = match.end()
        last_pos = pos
    if in_expr:
        raise TemplateError('No %s to finish last expression' % delimeters[1],
                            name=name, position=last_pos)
    part = s[last:]
    if part:
        chunks.append(part)
    if trim_whitespace:
        chunks = trim_lex(chunks)
    return chunks

lex.__doc__ = """
Lex a string into chunks:

    >>> lex('hey')
    ['hey']
    >>> lex('hey {{you}}')
    ['hey ', ('you', (1, 7))]
    >>> lex('hey {{')
    Traceback (most recent call last):
        ...
    tempita.TemplateError: No }} to finish last expression at line 1 column 7
    >>> lex('hey }}')
    Traceback (most recent call last):
        ...
    tempita.TemplateError: }} outside expression at line 1 column 7
    >>> lex('hey {{ {{')
    Traceback (most recent call last):
        ...
    tempita.TemplateError: {{ inside expression at line 1 column 10

""" if not PY2 else """
Lex a string into chunks:

    >>> lex('hey')
    ['hey']
    >>> lex('hey {{you}}')
    ['hey ', ('you', (1, 7))]
    >>> lex('hey {{')
    Traceback (most recent call last):
        ...
    TemplateError: No }} to finish last expression at line 1 column 7
    >>> lex('hey }}')
    Traceback (most recent call last):
        ...
    TemplateError: }} outside expression at line 1 column 7
    >>> lex('hey {{ {{')
    Traceback (most recent call last):
        ...
    TemplateError: {{ inside expression at line 1 column 10

"""

#statement_re = re.compile(r'^(?:if |elif |for |def |inherit |default |py:)')
statement_re = re.compile(r'^(?:if |elif |for |def |inherit |default)')
single_statements = frozenset(['else', 'endif', 'endfor', 'enddef', 'continue', 'break'])
trail_whitespace_re = re.compile(r'\n\r?[\t ]*$')
lead_whitespace_re = re.compile(r'^[\t ]*\n')

_statements = tuple("if elif for def inherit default else endif endfor"
                        " enddef continue break".split())


def trim_lex(tokens):
    last_trim = None
    for i in range(len(tokens)):
        current = tokens[i]
        if isinstance(tokens[i], basestring_):
            # we don't trim this
            continue
        item = current[0].strip()
        tokens[i] = tuple([item] + list(current[1:]))
        if not statement_re.search(item) and item not in single_statements:
            continue
        if not i:
            prev = ''
        else:
            prev = tokens[i - 1]
        if i + 1 >= len(tokens):
            next_chunk = ''
        else:
            next_chunk = tokens[i + 1]
        if (not
                isinstance(next_chunk, basestring_)
                or not isinstance(prev, basestring_)):
            continue
        prev_ok = not prev or trail_whitespace_re.search(prev)
        if i == 1 and not prev.strip():
            prev_ok = True
        if last_trim is not None and last_trim + 2 == i and not prev.strip():
            prev_ok = 'last'
        if (prev_ok
            and (not next_chunk or lead_whitespace_re.search(next_chunk)
                 or (i == len(tokens) - 2 and not next_chunk.strip()))):
            if prev:
                if ((i == 1 and not prev.strip()) or prev_ok == 'last'):
                    tokens[i - 1] = ''
                else:
                    m = trail_whitespace_re.search(prev)
                    # +1 to leave the leading \n on:
                    prev = prev[:m.start() + 1]
                    tokens[i - 1] = prev
            if next_chunk:
                last_trim = i
                if i == len(tokens) - 2 and not next_chunk.strip():
                    tokens[i + 1] = ''
                else:
                    m = lead_whitespace_re.search(next_chunk)
                    next_chunk = next_chunk[m.end():]
                    tokens[i + 1] = next_chunk
    return tokens

trim_lex.__doc__ = r"""
    Takes a lexed set of tokens, and removes whitespace when there is
    a directive on a line by itself:

       >>> tokens = lex('{{if x}}\nx\n{{endif}}\ny', trim_whitespace=False)
       >>> tokens
       [('if x', (1, 3)), '\nx\n', ('endif', (3, 3)), '\ny']
       >>> trim_lex(tokens)
       [('if x', (1, 3)), 'x\n', ('endif', (3, 3)), 'y']
    """ if not PY2 else r"""
    Takes a lexed set of tokens, and removes whitespace when there is
    a directive on a line by itself:

       >>> tokens = lex('{{if x}}\nx\n{{endif}}\ny', trim_whitespace=False)
       >>> tokens
       [('if x', (1, 3)), '\nx\n', ('endif', (3, 3)), '\ny']
       >>> trim_lex(tokens)
       [('if x', (1, 3)), 'x\n', ('endif', (3, 3)), 'y']
    """


def find_position(string, index, last_index, last_pos):
    """
    Given a string and index, return (line, column)
    """
    lines = string.count('\n', last_index, index)
    if lines > 0:
        column = index - string.rfind('\n', last_index, index)
    else:
        column = last_pos[1] + (index - last_index)
    return (last_pos[0] + lines, column)


def parse(s, name=None, line_offset=0, delimeters=None):

    if delimeters is None:
        delimeters = (Template.default_namespace['start_braces'],
                      Template.default_namespace['end_braces'])
    tokens = lex(s, name=name, line_offset=line_offset, delimeters=delimeters)
    result = []
    while tokens:
        next_chunk, tokens = parse_expr(tokens, name)
        result.append(next_chunk)
    #pprint(result)
    return result

parse.__doc__ = r"""
    Parses a string into a kind of AST

        >>> parse('{{x}}')
        [('expr', (1, 3), 'x')]
        >>> parse('foo')
        ['foo']
        >>> parse('{{if x}}test{{endif}}')
        [('cond', (1, 3), ('if', (1, 3), 'x', ['test']))]
        >>> parse(
        ...    'series->{{for x in y}}x={{x}}{{endfor}}'
        ... )  #doctest: +NORMALIZE_WHITESPACE
        ['series->',
            ('for', (1, 11), ('x',), 'y', ['x=', ('expr', (1, 27), 'x')])]
        >>> parse('{{for x, y in z:}}{{continue}}{{endfor}}')
        [('for', (1, 3), ('x', 'y'), 'z', [('continue', (1, 21))])]
        >>> parse(
        ...    '{{if x}}a{{elif y}}b{{else}}c{{endif}}'
        ... )  #doctest: +NORMALIZE_WHITESPACE
        [('cond', (1, 3), ('if', (1, 3), 'x', ['a']),
            ('elif', (1, 12), 'y', ['b']), ('else', (1, 23), None, ['c']))]

    Some exceptions::

        >>> parse('{{continue}}')
        Traceback (most recent call last):
            ...
        tempita.TemplateError: continue outside of for loop at line 1 column 3
        >>> parse('{{if x}}foo')
        Traceback (most recent call last):
            ...
        tempita.TemplateError: No {{endif}} at line 1 column 3
        >>> parse('{{else}}')
        Traceback (most recent call last):
            ...
        tempita.TemplateError: else outside of an if block at line 1 column 3
        >>> parse('{{if x}}{{for x in y}}{{endif}}{{endfor}}')
        Traceback (most recent call last):
            ...
        tempita.TemplateError: Unexpected endif at line 1 column 25
        >>> parse('{{if}}{{endif}}')
        Traceback (most recent call last):
            ...
        tempita.TemplateError: if with no expression at line 1 column 3
        >>> parse('{{for x y}}{{endfor}}')
        Traceback (most recent call last):
            ...
        tempita.TemplateError: Bad for (no "in") in 'x y' at line 1 column 3
    """ if not PY2 else r"""
    Parses a string into a kind of AST

        >>> parse('{{x}}')
        [('expr', (1, 3), 'x')]
        >>> parse('foo')
        ['foo']
        >>> parse('{{if x}}test{{endif}}')
        [('cond', (1, 3), ('if', (1, 3), 'x', ['test']))]
        >>> parse(
        ...    'series->{{for x in y}}x={{x}}{{endfor}}'
        ... )  #doctest: +NORMALIZE_WHITESPACE
        ['series->',
            ('for', (1, 11), ('x',), 'y', ['x=', ('expr', (1, 27), 'x')])]
        >>> parse('{{for x, y in z:}}{{continue}}{{endfor}}')
        [('for', (1, 3), ('x', 'y'), 'z', [('continue', (1, 21))])]
        >>> parse(
        ...    '{{if x}}a{{elif y}}b{{else}}c{{endif}}'
        ... )  #doctest: +NORMALIZE_WHITESPACE
        [('cond', (1, 3), ('if', (1, 3), 'x', ['a']),
            ('elif', (1, 12), 'y', ['b']), ('else', (1, 23), None, ['c']))]

    Some exceptions::

        >>> parse('{{continue}}')
        Traceback (most recent call last):
            ...
        TemplateError: continue outside of for loop at line 1 column 3
        >>> parse('{{if x}}foo')
        Traceback (most recent call last):
            ...
        TemplateError: No {{endif}} at line 1 column 3
        >>> parse('{{else}}')
        Traceback (most recent call last):
            ...
        TemplateError: else outside of an if block at line 1 column 3
        >>> parse('{{if x}}{{for x in y}}{{endif}}{{endfor}}')
        Traceback (most recent call last):
            ...
        TemplateError: Unexpected endif at line 1 column 25
        >>> parse('{{if}}{{endif}}')
        Traceback (most recent call last):
            ...
        TemplateError: if with no expression at line 1 column 3
        >>> parse('{{for x y}}{{endfor}}')
        Traceback (most recent call last):
            ...
        TemplateError: Bad for (no "in") in 'x y' at line 1 column 3
    """


def parse_expr(tokens, name, context=()):
    if isinstance(tokens[0], basestring_):
        return tokens[0], tokens[1:]
    expr, pos = tokens[0]
    expr = expr.strip()
    if expr in ('continue', 'break'):
        if 'for' not in context:
            raise TemplateError(
                'continue outside of for loop',
                position=pos, name=name)
        return (expr, pos), tokens[1:]
    elif expr.startswith('if '):
        return parse_cond(tokens, name, context)
    elif (expr.startswith('elif ')
          or expr == 'else'):
        raise TemplateError(
            '%s outside of an if block' % expr.split()[0],
            position=pos, name=name)
    elif expr in ('if', 'elif', 'for'):
        raise TemplateError(
            '%s with no expression' % expr,
            position=pos, name=name)
    elif expr in ('endif', 'endfor', 'enddef'):
        raise TemplateError(
            'Unexpected %s' % expr,
            position=pos, name=name)
    elif expr.startswith('for '):
        return parse_for(tokens, name, context)
    elif expr.startswith('default '):
        return parse_default(tokens, name, context)
    elif expr.startswith('inherit '):
        return parse_inherit(tokens, name, context)
    elif expr.startswith('def '):
        return parse_def(tokens, name, context)
    elif expr.startswith('#'):
        return ('comment', pos, tokens[0][0]), tokens[1:]
    return ('expr', pos, tokens[0][0]), tokens[1:]


def parse_cond(tokens, name, context):
    start = tokens[0][1]
    pieces = []
    context = context + ('if',)
    while 1:
        if not tokens:
            raise TemplateError(
                'Missing {{endif}}',
                position=start, name=name)
        if (isinstance(tokens[0], tuple) and tokens[0][0] == 'endif'):
            return ('cond', start) + tuple(pieces), tokens[1:]
        next_chunk, tokens = parse_one_cond(tokens, name, context)
        pieces.append(next_chunk)


def parse_one_cond(tokens, name, context):
    (first, pos), tokens = tokens[0], tokens[1:]
    content = []
    if first.endswith(':'):
        first = first[:-1]
    if first.startswith('if '):
        part = ('if', pos, first[3:].lstrip(), content)
    elif first.startswith('elif '):
        part = ('elif', pos, first[5:].lstrip(), content)
    elif first == 'else':
        part = ('else', pos, None, content)
    else:
        assert 0, "Unexpected token %r at %s" % (first, pos)
    while 1:
        if not tokens:
            raise TemplateError(
                'No {{endif}}',
                position=pos, name=name)
        if (isinstance(tokens[0], tuple)
            and (tokens[0][0] == 'endif'
                 or tokens[0][0].startswith('elif ')
                 or tokens[0][0] == 'else')):
            return part, tokens
        next_chunk, tokens = parse_expr(tokens, name, context)
        content.append(next_chunk)


def parse_for(tokens, name, context):
    first, pos = tokens[0]
    tokens = tokens[1:]
    context = ('for',) + context
    content = []
    assert first.startswith('for ')
    if first.endswith(':'):
        first = first[:-1]
    first = first[3:].strip()
    match = in_re.search(first)
    if not match:
        raise TemplateError(
            'Bad for (no "in") in %r' % first,
            position=pos, name=name)
    vars = first[:match.start()]
    if '(' in vars:
        raise TemplateError(
            'You cannot have () in the variable section of a for loop (%r)'
            % vars, position=pos, name=name)
    vars = tuple([
        v.strip() for v in first[:match.start()].split(',')
        if v.strip()])
    expr = first[match.end():]
    while 1:
        if not tokens:
            raise TemplateError(
                'No {{endfor}}',
                position=pos, name=name)
        if (isinstance(tokens[0], tuple) and tokens[0][0] == 'endfor'):
            return ('for', pos, vars, expr, content), tokens[1:]
        next_chunk, tokens = parse_expr(tokens, name, context)
        content.append(next_chunk)


def parse_default(tokens, name, context):
    first, pos = tokens[0]
    assert first.startswith('default ')
    first = first.split(None, 1)[1]
    parts = first.split('=', 1)
    if len(parts) == 1:
        raise TemplateError(
            "Expression must be {{default var=value}}; no = found in %r" %
            first, position=pos, name=name)
    var = parts[0].strip()
    if ',' in var:
        raise TemplateError(
            "{{default x, y = ...}} is not supported",
            position=pos, name=name)
    if not var_re.search(var):
        raise TemplateError(
            "Not a valid variable name for {{default}}: %r"
            % var, position=pos, name=name)
    expr = parts[1].strip()
    return ('default', pos, var, expr), tokens[1:]


def parse_inherit(tokens, name, context):
    first, pos = tokens[0]
    #print("'{first}'".format(**locals()))
    assert first.startswith('inherit ')
    expr = first.split(None, 1)[1]
    return ('inherit', pos, expr), tokens[1:]


def parse_def(tokens, name, context):
    first, start = tokens[0]
    tokens = tokens[1:]
    #print("'{first}'".format(**locals()))
    assert first.startswith('def ')
    first = first.split(None, 1)[1]
    func_name = first
    sig = ((), None, None, {})
    context = context + ('def',)
    content = []
    while 1:
        if not tokens:
            raise TemplateError(
                'Missing {{enddef}}',
                position=start, name=name)
        if (isinstance(tokens[0], tuple) and tokens[0][0] == 'enddef'):
            return ('def', start, func_name, sig, content), tokens[1:]
        next_chunk, tokens = parse_expr(tokens, name, context)
        content.append(next_chunk)


_fill_command_usage = """\
%prog [OPTIONS] TEMPLATE arg=value

Use py:arg=value to set a Python value; otherwise all values are
strings.
"""


def fill_command(args=None):
    import sys
    import optparse
    import pkg_resources
    import os
    if args is None:
        args = sys.argv[1:]
    parser = optparse.OptionParser(
        version=__version__,
        usage=_fill_command_usage)
    parser.add_option(
        '-o', '--output',
        dest='output',
        metavar="FILENAME",
        help="File to write output to (default stdout)")
    parser.add_option(
        '--html',
        dest='use_html',
        action='store_true',
        help="Use HTML style filling (including automatic HTML quoting)")
    parser.add_option(
        '--env',
        dest='use_env',
        action='store_true',
        help="Put the environment in as top-level variables")
    options, args = parser.parse_args(args)
    if len(args) < 1:
        print('You must give a template filename')
        sys.exit(2)
    template_name = args[0]
    args = args[1:]
    vars = {}
    if options.use_env:
        vars.update(os.environ)
    for value in args:
        if '=' not in value:
            print('Bad argument: %r' % value)
            sys.exit(2)
        name, value = value.split('=', 1)
        if name.startswith('py:'):
            name = name[:3]
            value = eval(value)
        vars[name] = value
    if template_name == '-':
        template_content = sys.stdin.read()
        template_name = '<stdin>'
    else:
        with open(template_name, 'rb') as f:
            template_content = f.read()
    if options.use_html:
        TemplateClass = HTMLTemplate
    else:
        TemplateClass = Template
    template = TemplateClass(template_content, name=template_name)
    result = template.substitute(vars)
    if options.output:
        with open(options.output, 'wb') as f:
            f.write(result)
    else:
        sys.stdout.write(result)


if __name__ == '__main__':
    fill_command()