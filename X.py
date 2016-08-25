# -*- coding: utf-8 -*-

# debug flag
DEBUG = False

basepath = os.path.dirname(os.path.abspath(__file__))

# helper functions
def identity(*args):
    if len(args) == 1:
        return args[0]  
    return args

def assoc(_d, key, value):
    from copy import deepcopy
    d = deepcopy(_d)
    d[key] = value
    return d


# spatialisation
import math
from numpy import linalg
    
halfpi = (0.5 * math.pi)

def angle2d(x1, y1,x2, y2):
        return halfpi - math.atan2(y1 - y2, x1 - x2)

def elevation(eye, point):
        return angle2d(eye[1], eye[2],
                       point[1],point[2])

def azimuth(eye, point):
        return angle2d(eye[0], eye[2],
                       point[0],point[2])

def calculate_position(eye, point,distance_offset=0):
        # distance shouldn't become 0 for ambisonics
        distance = max(0.01, linalg.norm(point-eye) + distance_offset)
        az = azimuth(eye, point)
        ele = elevation(eye, point)
        return distance, az, ele


# osc
import inspect
cmd_subfolder = os.path.realpath(os.path.abspath(os.path.join(os.path.split(inspect.getfile( inspect.currentframe() ))[0],"pyosc")))
if cmd_subfolder not in sys.path:
     sys.path.insert(0, cmd_subfolder)

from OSC import OSCClient, OSCMessage

client = OSCClient()
client.connect( ("localhost", 57120) )

def send_osc(addr, *args):
        msg = OSCMessage(addr)
        for d in args:
            msg.append(d)
        return client.send(msg)

# sound object management
"""
Abstract sound objects, the sound server (e.g., SuperCollider) decides what to do with them

Add new object with id and sound type:
/obj/new id sound_type

Modify existing object by id:
/obj/modify id [attribute_name attribute_value]*

Delete object by id:
/obj/delete id

Reset everything (delete all sound objects and samples):
/reset

Load sample at path to this id:
/sample/new id path

Switch HRTF decoder:
/decoder/set name

Set global volume between 0 and 1.0:
/volume/set volume
"""

# count up ids used to sync between python and sound server
id = 0

def load_sample(oid, path):
        if(oid == None):
                global id
                oid = id
                id += 1
        send_osc("/sample/new", oid, path)
        return dict(id=oid, path=path)

def make_sound_object(oid, type, *args):
        if(oid == None):
                global id
                oid = id
                id += 1
        send_osc("/obj/new", oid, type, *args)
        return dict(id=oid, type=type)

def modify_sound_object(obj, *args):
        send_osc("/obj/modify", obj['id'], *args)
        for i in range(int(len(args)/2)):
            attr = args[i]
            val = args[i+1]
            obj = assoc(obj, attr, val)
        return obj

def delete_sound_object(obj):
        send_osc("/obj/delete", obj['id'])
        return True

def position_sound_object(obj, dist, az, ele):
        obj = modify_sound_object(obj, "dist", dist, "az", az, "ele", ele)
        return obj

def reset_sound_objects():
    send_osc("/reset")

def set_decoder(name):
    print("setting decoder to " + name)
    send_osc("/decoder/set", name)

def set_volume(volume):
    send_osc("/volume/set", volume)


# chimera -> sonification mapping
import chimera
import numpy as np

import functools as ft

import datetime

def ch_get_real_eye():
        viewer = chimera.viewer
        camera = viewer.camera
        real_eye = chimera.Point(*camera.center)
        real_eye[2] = camera.eyeZ()
        return real_eye


ch_calculate_position = ft.partial(calculate_position, distance_offset=(-24))

def ch_position_sound_object(sobj, real_eye, coords):
        dist, az, ele = ch_calculate_position(real_eye, coords)
        return position_sound_object(sobj, dist, az, ele)

cleanup_fn = identity
mapping_objects = dict()


def m_test(models, objects):
        # init mapping
        if(len(objects) == 0):
                for model in models.list(modelTypes=[chimera.Molecule]):
                        for i,r in enumerate(model.residues):
                                sobj = make_sound_object(None, "atom")
                                sobj['ch_model_id'] = model.id
                                sobj['ch_residue'] = i  
                                objects[sobj['id']] = sobj
        # update positions
        real_eye = ch_get_real_eye()
        
        for key, sobj in objects.iteritems():
                obj = chimera.openModels.list(id=sobj['ch_model_id'])[0].residues[
                    sobj['ch_residue']]
                coords = obj.atoms[0].xformCoord()
                objects[key] = ch_position_sound_object(sobj, real_eye, coords)
        return objects


tFrame = 'new frame'
def m_bfactors_cleanup():
    print("cleaning up bfactors")

    for model in chimera.openModels.list(modelTypes=[chimera.Molecule]):
        for i,atom in enumerate(model.atoms):
            try:
               atom.color = atom.orig_color
            except:
                pass
    try:
            chimera.triggers.deleteHandler(tFrame, hFrame)
    except:
            pass

# cutoff for betafactors    
cutoff = 40.0


def m_bfactors_animation(trigger, additional, frameNo):
    onFrame = 0
    offFrame = 1
    for key, sobj in mapping_objects.iteritems():
        obj = chimera.openModels.list(id=sobj['ch_model_id'])[0].atoms[
            sobj['ch_atom']]
        lenAnim = sobj['len_anim']
        posAnimF = (frameNo % lenAnim)
        #posAnim = posAnimF/lenAnim

        if((onFrame == posAnimF) or (offFrame == posAnimF)):
            #print("tick", lenAnim)
            color = obj.orig_color
            if(onFrame == posAnimF):
                color = chimera.MaterialColor(1,0.5,0.2)
            obj.color = color


def m_bfactors(models, objects):
        # init mapping
        if(len(objects) == 0):
                for model in models.list(modelTypes=[chimera.Molecule]):
                        for i,atom in enumerate(model.atoms):
                                if(atom.bfactor > cutoff):
                                        rhfreq = (atom.bfactor - cutoff) / 10 + 1
                                        sobj = make_sound_object(None, "bfactor")
                                        sobj = modify_sound_object(sobj,
                                                                   "rhfreq", rhfreq,
                                                                   "freq", 440 + ((atom.bfactor - cutoff) * 10))
                                        sobj['len_anim'] =  int(round(15/rhfreq))
                                        sobj['ch_model_id'] = model.id
                                        sobj['ch_atom'] = i
                                        atom.orig_color = atom.color
                                        objects[sobj['id']] = sobj
                global hFrame
                hFrame = chimera.triggers.addHandler(tFrame,m_bfactors_animation, None)

                global cleanup_fn
                cleanup_fn = m_bfactors_cleanup

        # update positions
        real_eye = ch_get_real_eye()

        for key, sobj in objects.iteritems():
                obj = chimera.openModels.list(id=sobj['ch_model_id'])[0].atoms[
                    sobj['ch_atom']]
                coords = obj.xformCoord()
                dist, az, ele = ch_calculate_position(real_eye, coords)
                sobj = modify_sound_object(sobj,
                            "amp", np.interp(dist, [0,500], [0.8,0.01]))
                objects[key] = position_sound_object(sobj, dist, az, ele)
        return objects


### bfactor2
# cutoff for betafactors    
cutoff = 40.0

def m_bfactors2_animation(trigger, additional, frameNo):
    onFrame = 0
    offFrame = 1
    for key, sobj in mapping_objects.iteritems():
        obj = chimera.openModels.list(id=sobj['ch_model_id'])[0].atoms[
            sobj['ch_atom']]
        lenAnim = sobj['len_anim']
        posAnimF = (frameNo % lenAnim)
        #posAnim = posAnimF/lenAnim
        
        if((onFrame == posAnimF) or (offFrame == posAnimF)):
            #print("tick", lenAnim)
            color = obj.orig_color
                    
            if(onFrame == posAnimF):
                modify_sound_object(sobj, "gate", 1)
                color = chimera.MaterialColor(1,0.5,0.1)
            else:
                modify_sound_object(sobj, "gate", 0)
            obj.color = color


def m_bfactors2(models, objects):
        # init mapping
        if(len(objects) == 0):
                for model in models.list(modelTypes=[chimera.Molecule]):
                        for i,atom in enumerate(model.atoms):
                                if(atom.bfactor > cutoff):
                                        rhfreq = (atom.bfactor - cutoff) / 10 + 1
                                        sobj = make_sound_object(None, "bfactor2")
                                        sobj = modify_sound_object(sobj,
                                                                   "rhfreq", rhfreq,
                                                                   "freq", 440 + ((atom.bfactor - cutoff) * 10))
                                        sobj['len_anim'] = round(15/rhfreq)
                                        sobj['ch_model_id'] = model.id
                                        sobj['ch_atom'] = i
                                        atom.orig_color = atom.color
                                        objects[sobj['id']] = sobj
                global hFrame
                hFrame = chimera.triggers.addHandler(tFrame,m_bfactors2_animation, None)

                global cleanup_fn
                cleanup_fn = m_bfactors_cleanup

        # update positions
        real_eye = ch_get_real_eye()
        
        for key, sobj in objects.iteritems():
                obj = chimera.openModels.list(id=sobj['ch_model_id'])[0].atoms[
                    sobj['ch_atom']]
                coords = obj.xformCoord()
                dist, az, ele = ch_calculate_position(real_eye, coords)
                sobj = modify_sound_object(sobj,
                                           "amp", np.interp(dist, [0,500], [0.8,0.01]))
                objects[key] = position_sound_object(sobj, dist, az, ele)
        return objects


def m_earcons(models, objects):
        # cutoff for betafactors
        cutoff = 60.0

        # init mapping
        if(len(objects) == 0):
                objects["sample"] = load_sample(None, basepath + "/samples/creak.wav")
                for model in models.list(modelTypes=[chimera.Molecule]):
                        for i,atom in enumerate(model.atoms):
                                if(atom.bfactor > cutoff):
                                        sobj = make_sound_object(None, "sample",
                                                                 "freq", 440 + ((atom.bfactor - cutoff) * 10),
                                                                 "sample", objects["sample"]["id"]
                                                                 )
                                        sobj['ch_model_id'] = model.id
                                        sobj['ch_atom'] = i
                                        objects[sobj['id']] = sobj
        # update positions
        real_eye = ch_get_real_eye()
        
        for key, sobj in objects.iteritems():
            if(key != "sample"):
                obj = chimera.openModels.list(id=sobj['ch_model_id'])[0].atoms[
                    sobj['ch_atom']]
                coords = obj.xformCoord()
                dist, az, ele = ch_calculate_position(real_eye, coords)
                sobj = modify_sound_object(sobj,
                                           "sample", objects["sample"]["id"],
                                           "amp", np.interp(dist, [0,500], [0.8,0.01]))
                objects[key] = position_sound_object(sobj, dist, az, ele)
        return objects



def stop_mapping(objects):
        # double stop. probably one can go in the future
        for key, sobj in objects.iteritems():
                if(sobj.has_key('id')):
                        delete_sound_object(sobj)
        reset_sound_objects()
        cleanup_fn()

        return dict()

def set_mapping(new_map_fn):
    global mapping_objects
    mapping_objects = stop_mapping(mapping_objects)
    global mapping_fn
    mapping_fn = new_map_fn
    global cleanup_fn
    cleanup_fn = identity
    mapping_objects = mapping_fn(chimera.openModels, mapping_objects)


# clean the slate both on client and on sound server

reset_sound_objects()

mapping_fn = m_test



# chimera
import chimera

ch_models = dict()

def ch_add_model(model):
        return ch_delete_model(0)

def ch_modify_model():
        pass    

def ch_delete_model(id):
        print("deleting model ", id)
        objects = stop_mapping(mapping_objects)
        objects = mapping_fn(chimera.openModels, objects)
        return objects

def ch_change_view(viewer, models):
        objects = mapping_fn(chimera.openModels, mapping_objects)
        return objects


# chimera triggers
modelTrigger = u'Model'
viewerTrigger = u'Viewer'

try:
        chimera.triggers.deleteHandler(modelTrigger, modelHandler)
        chimera.triggers.deleteHandler(viewerTrigger, viewerHandler)
except:
        pass

# animation trigger
tFrame = 'new frame'
try:
        chimera.triggers.deleteHandler(tFrame, hFrame)
except:
        pass


def viewer_changed(trigger, additional, atomChanges):
        if DEBUG:
                print("triggered viewer changed")
        global mapping_objects
        mapping_objects = ch_change_view(chimera.viewer, chimera.openModels)
                                

openModelIds = set()

def models_changed(trigger, additional, changes):
        global openModelIds
        global mapping_objects
        for i in changes.modified:
                # TODO
                #print("triggered modified", changes.modified, changes.reasons)
                # send_osc("/model/modified", i.id, *changes.reasons)
                pass
        for i in changes.created:
                print("triggered create", changes.created, changes.reasons)
                mapping_objects = ch_add_model(i)
                newOpenModelIds = set()
                for model in chimera.openModels.list():
                        newOpenModelIds.add(model.id)
                openModelIds = newOpenModelIds
        for i in changes.deleted:
                print("triggered delete", changes.reasons)
                newOpenModelIds = set()
                
                for model in chimera.openModels.list():
                        newOpenModelIds.add(model.id)
                for id in openModelIds.difference(newOpenModelIds):
                        mapping_objects = ch_delete_model(id)
                openModelIds = newOpenModelIds


viewerHandler = chimera.triggers.addHandler(viewerTrigger,viewer_changed, None)
modelHandler = chimera.triggers.addHandler(modelTrigger, models_changed, None)


# GUI
import chimera

import Tkinter

from chimera.baseDialog import ModelessDialog

# last selected decoder
decoder = None  

# available decoders
decoders = [
    'KEMAR binaural 1',
    'KEMAR binaural 2',
    'UHJ stereo',
    'synthetic binaural',
]

mapping = None

mappings = {
    'Test mapping': m_test,
    'Betafactors': m_bfactors,
    'Betafactors v2': m_bfactors2,
    'Earcons': m_earcons,
}

default_volume = 0.5
volume = None


class DecoderDialog(ModelessDialog):    
    name = "decoder dialog"

    buttons = ("Apply", "Close")

    title = "Sonification settings"

    def fillInUI(self, parent):

        global decoder

        width = 16

        decoder = Tkinter.StringVar(parent)
        decoder.set(decoders[3])

        decoderLabel = Tkinter.Label(parent, text='Ambisonic Decoder')
        decoderLabel.grid(column=0, row=0)
        
        # Create the menu button and the option menu that it brings up.
        decoderButton = Tkinter.Menubutton(parent, indicatoron=1,
                                        textvariable=decoder, width=width,
                                        relief=Tkinter.RAISED, borderwidth=2)
        decoderButton.grid(column=1, row=0)
        decoderMenu = Tkinter.Menu(decoderButton, tearoff=0)
        
        #    Add radio buttons for all possible choices to the menu.
        for dec in decoders:
            decoderMenu.add_radiobutton(label=dec, variable=decoder, value=dec)
            
        #    Assigns the option menu to the menu button.
        decoderButton['menu'] = decoderMenu


        global mapping
        
        mapping = Tkinter.StringVar(parent)
        mapping.set(mappings.keys()[0])

        mappingLabel = Tkinter.Label(parent, text='Sonification Mapping')
        mappingLabel.grid(column=0, row=1)
        
        # Create the menu button and the option menu that it brings up.
        mappingButton = Tkinter.Menubutton(parent, indicatoron=1,
                                        textvariable=mapping, width=width,
                                        relief=Tkinter.RAISED, borderwidth=2)
        mappingButton.grid(column=1, row=1)
        mappingMenu = Tkinter.Menu(mappingButton, tearoff=0)
        
        #    Add radio buttons for all possible choices to the menu.
        for mapname in mappings.keys():
            mappingMenu.add_radiobutton(label=mapname, variable=mapping, value=mapname)
            
        #    Assigns the option menu to the menu button.
        mappingButton['menu'] = mappingMenu


        global volume

        volume = Tkinter.DoubleVar(parent)
        volume.set(default_volume)

        label = Tkinter.Label(parent, text='Volume')
        label.grid(column=0,row=2)

        scale = Tkinter.Scale(parent, from_=0, to=1.0, width=width,
                              resolution=0.01, orient=Tkinter.HORIZONTAL,
                              variable=volume, showvalue=0,
                              command=lambda self: set_volume(volume.get()))
        scale.grid(column=1, row=2)

    def Apply(self):
        set_decoder(decoder.get())
        print("setting mapping to " + mapping.get())
        set_mapping(mappings[mapping.get()])

if(chimera.dialogs.find(DecoderDialog.name) == None):
    chimera.dialogs.register(DecoderDialog.name, DecoderDialog)
else:
    chimera.dialogs.reregister(DecoderDialog.name, DecoderDialog)

chimera.dialogs.display(DecoderDialog.name)
