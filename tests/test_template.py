# -*- coding: utf-8 -*-

from pytest import raises
from tempita_lite import *


def test_simple():
    result = sub('Hi {{name}}', name='Ian')
    assert result == 'Hi Ian'
    result = Template('Hi {{repr(name)}}').substitute(name='Ian')
    assert result == "Hi 'Ian'"
    with raises(TypeError):
        result = Template('Hi {{name+1}}').substitute(name='Ian')

def test_delimiter():
    result = sub('Hi ${name}', name='Ian', delimeters=('${', '}'))
    assert result == 'Hi Ian'
    result = Template('Hi $[[repr(name)]]', delimeters=('$[[', ']]')).substitute(name='Ian')
    assert result == "Hi 'Ian'"

def test_pipe():
    result = sub('Hi {{name|repr}}', name='Ian')
    assert result == "Hi 'Ian'"

def test_None():
    result = sub('Hi {{name}}', name=None)
    assert result == 'Hi '

def test_if():
    t = Template('{{if x}}{{y}}{{else}}{{z}}{{endif}}')
    r = t.substitute(x=1, y=2, z=3)
    assert r == '2'
    r = t.substitute(x=0, y=2, z=3)
    assert r == '3'
    t = Template('{{if x > 0}}positive{{elif x < 0}}negative{{else}}zero{{endif}}')
    r = t.substitute(x=1), t.substitute(x=-10), t.substitute(x=0)
    assert r == ('positive', 'negative', 'zero')

def test_for():
    t = Template('{{for i in x}}i={{i}}\n{{endfor}}')
    r = t.substitute(x=range(3))
    assert r == 'i=0\ni=1\ni=2\n'
    t = Template('{{for a, b in sorted(z.items()):}}{{a}}={{b}},{{endfor}}')
    r = t.substitute(z={1: 2, 3: 4})
    assert r == '1=2,3=4,'
    t = Template('{{for i in x}}{{if not i}}{{break}}'
                 '{{endif}}{{i}} {{endfor}}')
    r = t.substitute(x=[1, 2, 0, 3, 4])
    assert r == '1 2 '
    t = Template('{{for i in x}}{{if not i}}{{continue}}'
                 '{{endif}}{{i}} {{endfor}}')
    r = t.substitute(x=[1, 2, 0, 3, 0, 4])
    assert r == '1 2 3 4 '

def test_error():
    with raises(TemplateError):
        t = Template('{{if x}}', name='foo.html')
    with raises(TemplateError):
        t = Template('{{for x}}', name='foo2.html')

def test_html():
    r = sub_html('hi {{name}}', name='<foo>')
    assert r == 'hi &lt;foo&gt;'
    r = sub_html('hi {{name}}', name=html('<foo>'))
    assert r == 'hi <foo>'
    r = sub_html('hi {{name|html}}', name='<foo>')
    assert r == 'hi <foo>'

def test_html_functions():
    t = HTMLTemplate('<a href="article?id={{id|url}}" {{attr(class_=class_)}}>')
    r = t.substitute(id=1, class_='foo')
    assert r == '<a href="article?id=1" class="foo">'
    r = t.substitute(id='with space', class_=None)
    assert r == r'<a href="article?id=with%20space" >'

def test_strip():
    r = sub('{{if 1}}\n{{x}}\n{{endif}}\n', x=0)
    assert r == '0\n'
    r = sub('{{if 1}}x={{x}}\n{{endif}}\n', x=1)
    assert r == 'x=1\n'
    r = sub('{{if 1}}\nx={{x}}\n{{endif}}\n', x=1)
    assert r == 'x=1\n'
    r = sub('  {{if 1}}  \nx={{x}}\n  {{endif}}  \n', x=1)
    assert r == 'x=1\n'

def test_default():
    r = sub('{{default x=1}}{{x}}', x=2)
    assert r == '2'
    r = sub('{{default x=1}}{{x}}')
    assert r == '1'
    print(locals())
    with raises(NameError):
        r = sub('{{x}}')
        print(r)

def test_comment():
    r = sub('Test=x{{#whatever}}')
    assert r == 'Test=x'


def test_inherit():
    super_test = Template('''\
    This is the parent {{master}}.
    The block: {{self.block}}
    Then the body: {{self.body}}
    ''')
    def get_template(name, from_template):
        assert name == "super_test"
        return super_test
    tmpl = Template('''
    {{inherit "super_"+master}}
    Hi there! {{def block}}some text{{enddef}}
    ''', get_template=get_template)
    r = tmpl.substitute(master='test').strip()
    assert r == """This is the parent test.
    The block: some text
    Then the body:     Hi there!"""

def test_whitespace():
    tmpl = Template('''\
{{for i, item in enumerate(['a', 'b'])}}
    {{if i % 2 == 0}}
  <div class='even'>
    {{else}}
  <div class='odd'>
    {{endif}}
    {{item}}
  </div>
{{endfor}}''')
    r = tmpl.substitute()
    assert r == """\
  <div class='even'>
    a
  </div>
  <div class='odd'>
    b
  </div>
"""
