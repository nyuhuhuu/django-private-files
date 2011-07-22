import mimetypes
import os
import posixpath
import re
import urllib

from django.http import HttpResponse, Http404, HttpResponseRedirect, HttpResponseNotModified
from django.core.exceptions import PermissionDenied
from django.db.models import get_model
from django.shortcuts import get_object_or_404
from django.contrib.admin.util import unquote
from django.views.static import was_modified_since
from django.utils.http import http_date, parse_http_date
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from private_files.signals import pre_download

if not getattr(settings, 'FILE_PROTECTION_METHOD', False):
        raise ImproperlyConfigured('You need to set FILE_PROTECTION_METHOD in your project settings')


def _handle_basic(request, path, url, attachment=True):
    mimetype, encoding = mimetypes.guess_type(path)
    mimetype = mimetype or 'application/octet-stream'
    statobj = os.stat(path)
    if not was_modified_since(request.META.get('HTTP_IF_MODIFIED_SINCE'),
                            statobj.st_mtime, statobj.st_size):
        return HttpResponseNotModified(mimetype=mimetype)
    basename = os.path.basename(path)
    buff = open(path)
    response = HttpResponse(buff.read(), mimetype=mimetype)
    response["Last-Modified"] = http_date(statobj.st_mtime)
    response["Content-Length"] = statobj.st_size
    if attachment:
        response['Content-Disposition'] = 'attachment; filename=%s'%basename
    if encoding:
        response["Content-Encoding"] = encoding
    buff.close()
    return response


def _handle_nginx(request, path, url, attachment=True):
    basename = os.path.basename(path)
    mimetype, encoding = mimetypes.guess_type(path)
    mimetype = mimetype or 'application/octet-stream'
    statobj = os.stat(path)
    response = HttpResponse()
    response['Content-Type'] = mimetype
    if attachment:
        response['Content-Disposition'] = 'attachment; filename=%s'%basename
    response["X-Accel-Redirect"] = url
    response['Content-Length'] = statobj.st_size
    return response


def _handle_xsendfile(request, path, url, attachment=True):
    basename = os.path.basename(path)
    mimetype, encoding = mimetypes.guess_type(path)
    mimetype = mimetype or 'application/octet-stream'
    statobj = os.stat(path)
    response = HttpResponse()
    response['Content-Type'] = mimetype
    if attachment:
        response['Content-Disposition'] = 'attachment; filename=%s'%basename
    response["X-Sendfile"] = path
    response['Content-Length'] = statobj.st_size
    return response


def _handle_method(method, request, instance, field_name):
    field_file  = getattr(instance, field_name)
    url = "/%s" % unicode(field_file)
    return method(request, field_file.path, url, attachment=field_file.attachment)


METHODS = {
        'basic': _handle_basic,
        'nginx': _handle_nginx,
        'xsendfile': _handle_xsendfile
        }

try:
    METHOD = METHODS[settings.FILE_PROTECTION_METHOD]
except KeyError:
    raise ImproperlyConfigured('FILE_PROTECTION_METHOD in your project settings needs to be set to one of %s'%(METHODS.keys()))

def get_file(request, app_label, model_name, field_name, object_id, filename):
    model = get_model(app_label, model_name)
    instance = get_object_or_404(model, pk =unquote(object_id))
    condition = getattr(instance, field_name).condition
    if not model:
        raise Http404("")
    if not hasattr(instance, field_name):
        raise Http404("")
    if condition(request, instance):
        pre_download.send(sender = model, instance = instance, field_name = field_name, request = request)
        return _handle_method(METHOD, request, instance, field_name)
    else:
        raise PermissionDenied()
