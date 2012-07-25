#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
#  Copyright (C) 2012 Russ Dill <Russ.Dill@asu.edu>
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.

import pymodbus.client.sync
import pymodbus.factory
import pymodbus.client.async
import pymodbus.transaction
import sys
import math
import time

import twisted.internet.gtk3reactor
twisted.internet.gtk3reactor.install()

import twisted.internet.reactor
import twisted.internet.serialport
import twisted.internet.protocol

from gi.repository import Gtk, GObject

import matplotlib.figure
import matplotlib.ticker
from matplotlib.backends.backend_gtk3cairo import FigureCanvasGTK3Cairo as FigureCanvas

inty = [ 'T Tc', 'R Tc', 'J Tc', 'Wre3-Wre5', 'B Tc', 'S Tc', 'K Tc', 'E Tc', 'Pt100',
         'Cu50', '0-375Ω', '0-80mV', '0-30mV', '0-5V', '1-5V', '0-10V', '0-10mA', '0-20mA', '4-20mA' ]

alarm_modes = [ 'Program', 'High alarm', 'Low alarm', 'Deviation high alarm', 'Deviation low alarm',
                'Band alarm', 'Deviation high/low alarm', None, None, None, None, None, None, None, None, None,
                'High alarm (w/hold)', 'Low alarm (w/hold)', 'Deviation high alarm (w/hold)',
                'Deviation low alarm (w/hold)', 'Band alarm (w/hold)', 'Deviation high/low alarm (w/hold)' ]

# For SSR, use Duty cycle
output_type = { '0-10mA': 0, '4-20mA': 1, '0-20mA': 2, 'Duty cycle (s)': (3,100) }

run_modes = { 'Energize J1': -1011, 'De-energize J1': -1010, 'Energize J2': -1021, 'De-energize J2': -1020,
              'Jump': (-64,-1), 'Pause': 0, 'Run': (1,9999) }

#    Symbol  Description                           Address   Range           Factory set value

registers = {
    'SV':  ("Set value",                          0x0000,   (-1999,9999),   50,     None),
    'AL1': ("First alarm set value",              0x0001,   (-1999,9999),   60,     None),
    'AL2': ("Second alarm set value",             0x0002,   (-1999,9999),   40,     None),
    'At':  ("Auto tuning ON/OFF",                 0x0003,   ["Off", "On"],"Off",    1.0),

    'PV':   ("Measured process value",            0x0164,   (-1999,9999),   None,   1.0),
    'dSV':  ("Dynamic set value",                 0x0168,   (-1999,9999),   None,   1.0),
    'OUT':  ("Output value",                      0x016C,   (0.0,100.0),    None,   0.1),
    'Pr+t':("Curve segment number and time",      0x0190,   None,           None,   None),

    'AL1y': ("First alarm type",                  0x1000,   alarm_modes, 'High alarm',1.0),
    'AL1C': ("First alarm hysteresis",            0x1001,   (0,9999),       0,     None),
    'AL2y': ("Second alarm type",                 0x1002,   alarm_modes, 'Low alarm',1.0),
    'AL2C': ("Second alarm hysteresis",           0x1003,   (0,9999),       0,     None),
    'P':   ("Proportional band",                  0x1004,   (0.1,300.0),    20,    0.1),
    'I':   ("Integral time",                      0x1005,   (0,2000),       100,   1.0),
    'd':   ("Derivative time",                    0x1006,   (0,999),        20,    1.0),
    'Ct':  ("PID proportion cycle",               0x1007,   (0,100),        1,     1.0),#S
    'SF':  ("Anti-reset windup",                  0x1008,   (0,9999),       50,    None),#°C
    'Pd':  ("Derivative amplitude limit",         0x1009,   (0.1,0.9),      0.5,   0.1),
    'bb':  ("Range of PID action",                0x100A,   (0,9999),       1000,  1.0),#°C
    'outL': ("Output low limit",                  0x100B,   (0,100.0),      0,     0.1),#%
    'outH': ("Output high limit",                 0x100C,   (0,100.0),      100,   0.1),#%
    'nout': ("Output value when input is abnormal",0x100D,  (0,100),        20,    1.0),#%
    # Added to Pv
    'Psb': ("PV bias",                            0x100E,   (-1999,9999),   0,     None),
    'FILt': ("Digital filter",                    0x100F,   (0,3),          1,     1.0),

    'Inty': ("Input signal type",                 0x2000,   inty,                              'Pt100',1.0),
    'PvL': ("Display low limit",                  0x2001,   (-1999,9999),                      0,      None),
    'PvH': ("Display high limit",                 0x2002,   (-1999,9999),                      500,    None),
    'dot': ("Decimal point position",             0x2003,   (0,3),                             1,      1.0),
    'rd':  ("Direct/reverse action",              0x2004,   ['reverse action', 'direct action'],'reverse action',1.0),
    'obty': ("Re-transmission output type",       0x2005,   ['0-10mA','4-20mA','0-20mA'],      '0-20mA',1.0),
    'obL': ("Re-transmission low limit",          0x2006,   (-1999,9999),                      0,      None),
    'obH': ("Re-transmission high limit",         0x2007,   (-1999,9999),                      500,    None),
    'oAty': ("Output type",                       0x2008,   output_type,                       '0-20mA',1.0),
    # FIMXE: Correct order of options?
    'EL':  ("Extraction",                         0x2009,   ['extraction', 'no extraction'],   'no extraction', 1.0),
    'SS':  ("Small signal removal",               0x200A,   (0,100),                           0,      1.0),#%
    'rES': ("Delay startup",                      0x200B,   (0,120),                           0,      1.0),#S
    'uP':  ("Power fail process",                 0x200C,   ['Reset', 'Resume'],               'Resume',1.0), # Reset to PrL, vs Resume last step
    # NB: PID auto tuning function is valid, and P, I, and D in 0036 parameter group is valid (0x1004-0x1006),
    # all parameters in 0037 parameter group are invalid (0x30xx).
    'ModL': ("Work mode",                         0x200D,   [ 'SV', 'S-SV', 'M-SV', 'S-PV', 'M-PV'],'SV',1.0),
    'PrL': ("First step",                         0x200E,   (1,63),                            1,      1.0),
    'PrH': ("Last step",                          0x200F,   (2,64),                            63,     1.0),
    # NB: Manual errors/inconsistencies re the last three entries
    'corf': ("Celsius/Fahrenheit",                0x2010,   ['C', 'F'],                        'C',    1.0),
    'Id':  ("Communication address",              0x2011,   (1,64),                            5,      1.0),
    'bAud': ("Communication baud rate",           0x2012,   ['1200','2400','4800','9600'],     '9600', 1.0),
}

#
# This gist is released under Creative Commons Public Domain Dedication License CC0 1.0
# http://creativecommons.org/publicdomain/zero/1.0/
#

from twisted.internet import defer, reactor

class TimeoutError(Exception):
    """Raised when time expires in timeout decorator"""

def timeout(secs):
    """
    Decorator to add timeout to Deferred calls
    """
    def wrap(func):
        @defer.inlineCallbacks
        def _timeout(*args, **kwargs):
            rawD = func(*args, **kwargs)
            if not isinstance(rawD, defer.Deferred):
                defer.returnValue(rawD)

            timeoutD = defer.Deferred()
            timesUp = reactor.callLater(secs, timeoutD.callback, None)

            try:
                rawResult, timeoutResult = yield defer.DeferredList([rawD, timeoutD], fireOnOneCallback=True, fireOnOneErrback=True, consumeErrors=True)
            except defer.FirstError, e:
                #Only rawD should raise an exception
                assert e.index == 0
                timesUp.cancel()
                e.subFailure.raiseException()
            else:
                #Timeout
                if timeoutD.called:
                    rawD.cancel()
                    raise TimeoutError("%s secs have expired" % secs)

            #No timeout
            timesUp.cancel()
            defer.returnValue(rawResult)
        return _timeout
    return wrap
#
# End gist
#

def ordinal(n):
    if 10 <= n % 100 < 20:
        return str(n) + 'th'
    else:
        return str(n) + {1 : 'st', 2 : 'nd', 3 : 'rd'}.get(n % 10, "th")

for i in range(0, 9):
    step = ordinal(i+1)
    registers['P'+str(i+1)] = (step+' P', 0x3000 + i*3, (0.1,300.0), 20.0, 0.1)
    registers['I'+str(i+1)] = (step+' I', 0x3001 + i*3, (0,2000), 100, 1.0)
    registers['d'+str(i+1)] = (step+' D', 0x3002 + i*3, (0,1000), 20, 1.0)

for i in range(0, 64):
    registers['C-%02d'%(i+1)] = ('PID number of %s step' % step, 0x4000 + i*3, (0,8), 1, 1.0)
    registers['t-%02d'%(i+1)] = ('Run time of %s step' % step, 0x4001 + i*3, run_modes, 0, 1.0)
    registers['Sv%02d'%(i+1)] = ('SV of %s step' % step, 0x4002 + i*3, (-1999,9999), 0, 1.0)

#Note for reprogramming, Slot PrH will not count down.
# Set ModL to SV
# Set PrH to t 1
# Set current program to Jump to PrH
# Set ModL to S-SV
# Set ModL to SV
# Reprogram
# Set PrH to Jump PrL
# Reprogram PrH
# Set ModL to S-SV

# It does not appear there is a way to cancel a pause.

bits = ['SV', 'A/M', 'R/D', 'setting', 'abnormal', 'AL2', 'AL1', 'AT']

bit_desc = {'SV':       'User modifying SV',
            'A/M':      'Manual Control',
            'R/D':      'Heat/cool',
            'setting':  'User modifying settings',
            'abnormal': 'Probe input error',
            'AL2':      'Alarm 2 active',
            'AL1':      'Alarm 1 active',
            'AT':       'Auto-tune active'}

class ExampleProtocol(pymodbus.client.async.ModbusClientProtocol, GObject.GObject):

    __gsignals__ = {
        'changed': (GObject.SIGNAL_RUN_FIRST, None, (str,object,float,)),
        'process-start': (GObject.SIGNAL_RUN_FIRST, None, ()),
        'process-end': (GObject.SIGNAL_RUN_FIRST, None, ())
    }

    def __init__(self):
        GObject.GObject.__init__(self)
        framer = pymodbus.transaction.ModbusRtuFramer(pymodbus.factory.ClientDecoder())
        pymodbus.client.async.ModbusClientProtocol.__init__(self, framer)
        self.unit_id = 5
        self.reg_iter = registers.iteritems()
        self.is_busy = 0
        #twisted.internet.reactor.callLater(0, self.cycle)

    def busy(self):
        self.is_busy += 1
        if self.is_busy == 1:
            self.emit('process-start')

    def unbusy(self):
        self.is_busy -= 1
        if self.is_busy == 0:
            self.emit('process-end')
        assert self.is_busy >= 0

    @twisted.internet.defer.inlineCallbacks
    def flags(self):
        try:
            self.busy()
            response = yield timeout(1.0)(self.read_coils)(0, 8, self.unit_id)
            val = dict(zip(bits, response.bits))
            self.emit('changed', 'flags', val, 1.0)
        except TimeoutError, e:
            self.reset()
            raise e
        finally:
            d = twisted.internet.defer.Deferred()
            twisted.internet.reactor.callLater(0.004, d.callback, None)
            yield d
            self.unbusy()
        twisted.internet.defer.returnValue(val)

    def reset(self):
        self.connectionLost('transaction error')
        self.framer._ModbusRtuFramer__buffer = ''
        self.framer._ModbusRtuFramer__header = {}
        self.connectionMade()

    @twisted.internet.defer.inlineCallbacks
    def holding_read(self, reg, suppress=False):
        self.busy()
        try:
            if type(reg) is int:
                register = None
                addr = reg
            else:
                register = registers[reg]
                addr = register[1]
            try:
                response = yield timeout(0.5)(self.read_holding_registers)(addr, 2, self.unit_id)
            except TimeoutError, e:
                self.reset()
                raise e

            mult = 1.0
            if reg == 'Pr+t':
                Pr = response.registers[0]>>8
                t = ((response.registers[0] & 0xff)<<8) + (response.registers[1]>>8)
                val = (Pr, t)
            else:
                value = response.registers[0]
                value = value - 0x10000 if value > 0x7fff else value
                mult = 10**-response.registers[1]
                value *= mult
                if register is None:
                    val = value
                    reg = '0x%04x' % reg
                else:
                    val = None
                    if type(register[2]) is tuple:
                        if value >= register[2][0] and value <= register[2][1]:
                            val = value
                        else:
                            pass
                    elif type(register[2]) is list:
                        try:
                            val = register[2][value]
                        except:
                            pass
                    elif type(register[2]) is dict:
                        for key, item in register[2].iteritems():
                            if type(item) is tuple:
                                if value >= item[0] and value <= item[1]:
                                    val = (key, value)
                                    break
                            elif item == value:
                                val = key
                                break
            if not suppress:
                self.emit("changed", reg, val, mult)
            d = twisted.internet.defer.Deferred()
            twisted.internet.reactor.callLater(0.004, d.callback, None)
            yield d
        finally:
            self.unbusy()
        twisted.internet.defer.returnValue((val, mult))

    @twisted.internet.defer.inlineCallbacks
    def raw(self, reg, value):
        self.busy()
        try:
            yield self.holding_write(reg, value)
            yield self.holding_read(reg)
        finally:
            self.unbusy()

    @twisted.internet.defer.inlineCallbacks
    def holding_write(self, reg, value):
        self.busy()
        try:
            d = None
            if reg == 'A/M':
                d = timeout(0.5)(self.write_coil)(1, int(value), self.unit_id)
            elif reg == 'NAT':
                d = timeout(0.5)(self.write_coil)(0, int(value), self.unit_id)
            else:
                register = registers[reg]
                val = None
                if type(register[2]) is tuple:
                    if register[2][0] <= float(value) <= register[2][1]:
                        val = float(value)
                elif type(register[2]) is list:
                    try:
                        val = register[2].index(value)
                    except:
                        pass
                elif type(register[2]) is dict:
                    try:
                        if type(value) is tuple:
                            value, idx = value
                        item = register[2][value]
                        if type(item) is tuple:
                            if item[0] <= float(idx) <= item[1]:
                                val = float(idx)
                        else:
                            val = item
                    except:
                        pass

                if val is None:
                    raise Exception('invalid argument')
                else:
                    d = self.holding_read(reg, suppress=True)
                    _, mult = yield d
                    val /= mult
                    if val < 0:
                        val += 0x10000
                    d = timeout(0.5)(self.write_registers)(register[1], [int(val+1e-6), 0], self.unit_id)
            try:
                yield d
            except TimeoutError, e:
                self.reset()
                raise e
            d = twisted.internet.defer.Deferred()
            twisted.internet.reactor.callLater(0.004, d.callback, None)
            yield d
        finally:
            self.unbusy()

class SerialModbusClient(twisted.internet.serialport.SerialPort):
    def __init__(self, *args, **kwargs):
        self.protocol = ExampleProtocol()
        self.decoder = pymodbus.factory.ClientDecoder()
        twisted.internet.serialport.SerialPort.__init__(self, self.protocol, *args, **kwargs)
        self.flushInput()

class PIDTab(Gtk.Table):
    def __init__(self, pid):
        Gtk.Table.__init__(self, len(self.regs), 4)
        self.spin = {}
        self.adj = {}
        self.adj_old = {}
        self.combo = {}
        self.pid = pid
        self.from_pid = False
        self.ignore_combo = False
        self.refreshed = False
        pid.connect('changed', self.changed)
        for row, n in enumerate(self.regs):
            reg = registers[n]

            label = Gtk.Label(n)
            label.set_alignment(0, 0.5)
            self.attach(label, 0, 1, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)

            label = Gtk.Label(reg[0])
            label.set_alignment(0, 0.5)
            self.attach(label, 1, 2, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)

            adjustment = Gtk.Adjustment()
            spin = Gtk.SpinButton()
            spin.set_adjustment(adjustment)
            self.attach(spin, 3, 4, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)
            self.spin[n] = spin
            self.adj[n] = adjustment
            self.adj_old[n] = 0

            if type(reg[2]) is list or type(reg[2]) is dict:
                combo = Gtk.ComboBoxText()
                for text in reg[2]:
                    if text is not None:
                        combo.append_text(text)
                combo.connect('changed', self.combo_changed, n)
                self.combo[n] = combo
                spin.set_sensitive(False)
                self.attach(combo, 2, 3, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)
            else:
                adjustment.set_lower(reg[2][0])
                adjustment.set_upper(reg[2][1])
                adjustment.set_step_increment(1)

            adjustment.connect('value-changed', self.adj_changed, n)

    def changed(self, pid, n, val, mult):
        if n not in self.regs:
            return
        self.from_pid = True
        reg = registers[n]
        if type(reg[2]) is list or type(reg[2]) is dict:
            idx = None
            if type(val) is tuple:
                val, idx = val
            model = self.combo[n].get_model()
            for i, row in enumerate(model):
                if row[0] == val:
                    self.combo[n].set_active(i)
                    break
            if idx is not None:
                self.spin[n].set_value(idx)

        else:
            self.adj[n].set_step_increment(mult)
            if mult < 1.0:
                self.spin[n].set_digits(-math.log10(mult))
            else:
                self.spin[n].set_digits(0)
            self.adj[n].set_value(val)
        self.from_pid = False

    def combo_changed(self, combo, n):
        curr = combo.get_active_text()
        reg = registers[n]
        if self.from_pid:
            if type(reg[2]) is dict:
                r = reg[2][curr]
                if type(r) is tuple:
                    self.adj[n].set_lower(r[0])
                    self.adj[n].set_upper(r[1])
                    self.spin[n].set_digits(0)
                    self.adj[n].set_step_increment(1)
                    self.spin[n].set_sensitive(True)
                else:
                    self.spin[n].set_sensitive(False)
        elif not self.ignore_combo:
            self.ignore_combo = True
            combo.set_active(-1)
            if type(reg[2]) is dict and type(reg[2][curr]) is tuple:
                r = reg[2][curr]
                val = self.adj[n].get_value()
                val = max(val, r[0])
                val = min(val, r[1])
                curr = (curr, val)
            d = self.pid.raw(n, curr)
            d.addErrback(lambda x: None)
        else:
            self.ignore_combo = False

    def adj_changed(self, adj, n):
        if not self.from_pid:
            val = adj.get_value()
            self.ignore_adj = True
            reg = registers[n]
            if type(reg[2]) is dict:
                curr = self.combo[n].get_active_text()
                if type(reg[2][curr]) is tuple:
                    val = (curr, val)
            d = self.pid.raw(n, val)
            d.addErrback(lambda x: adj.set_value(self.adj_old[n]))
        else:
            self.adj_old[n] = adj.get_value()

    def on_show(self):
        if not self.refreshed:
            self.refresh()

    def refresh(self):
        d = self._refresh()
        d.addErrback(lambda x: None)

    @twisted.internet.defer.inlineCallbacks
    def _refresh(self):
        self.pid.busy()
        try:
            for n in self.regs:
                yield self.pid.holding_read(n)
            self.refreshed = True
        finally:
            self.pid.unbusy()

class Function(PIDTab):
    regs = [ 'Inty', 'PvL', 'PvH', 'dot', 'rd', 'obty', 'obL', 'obH', 'oAty',
             'EL', 'SS', 'rES', 'uP', 'ModL', 'PrL', 'PrH', 'corf', 'Id', 'bAud' ]
    def __init__(self, pid):
        PIDTab.__init__(self, pid)

class Work(PIDTab):
    regs = [ 'AL1y', 'AL1C', 'AL2y', 'AL2C', 'P', 'I', 'd', 'Ct', 'SF', 'Pd',
             'bb', 'outL', 'outH', 'nout', 'Psb', 'FILt' ]
    def __init__(self, pid):
        PIDTab.__init__(self, pid)

class Control(PIDTab):
    regs = [ 'SV', 'AL1', 'AL2', 'At' ]
    def __init__(self, pid):
        PIDTab.__init__(self, pid)
        # FIMXE: Add NAT and A/T action

class Status(Gtk.Table):
    regs = [ 'PV', 'dSV', 'OUT', 'Pr+t', 'flags' ]
    def __init__(self, pid):
        Gtk.Table.__init__(self, 5, 3)
        self.labels = {}
        self.refreshed = False
        self.pid = pid
        for row, n in enumerate([ 'PV', 'dSV', 'OUT', 'Pr', 't']):
            label = Gtk.Label(n)
            label.set_alignment(0, 0.5)
            self.attach(label, 0, 1, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)

            if n == 'Pr':
                text = 'Step'
            elif n == 't':
                text = 'Step time elapsed'
            else:
                text = registers[n][0]

            label = Gtk.Label(text)
            label.set_alignment(0, 0.5)
            self.attach(label, 1, 2, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)

            label = Gtk.Label()
            label.set_alignment(0, 0.5)
            self.attach(label, 2, 3, row, row+1, yoptions=Gtk.AttachOptions.SHRINK)
            self.labels[n] = label

        for row, n in enumerate(bits):
            label = Gtk.Label(n)
            label.set_alignment(0, 0.5)
            self.attach(label, 0, 1, row+5, row+6, yoptions=Gtk.AttachOptions.SHRINK)

            label = Gtk.Label(bit_desc[n])
            label.set_alignment(0, 0.5)
            self.attach(label, 1, 2, row+5, row+6, yoptions=Gtk.AttachOptions.SHRINK)

            label = Gtk.Label()
            label.set_alignment(0, 0.5)
            self.attach(label, 2, 3, row+5, row+6, yoptions=Gtk.AttachOptions.SHRINK)
            self.labels[n] = label

        pid.connect('changed', self.changed)

    def changed(self, pid, n, val, mult):
        if n not in self.regs:
            return
        if n == 'Pr+t':
            self.labels['Pr'].set_text(str(val[0]))
            self.labels['t'].set_text(str(val[1]))
        elif n == 'flags':
            for key, item in val.iteritems():
                self.labels[key].set_text(str(item))
        else:
            if mult == 0.1:
                self.labels[n].set_text('%.1f' % val)
            else:
                self.labels[n].set_text('%d' % val)

    def on_show(self):
        if not self.refreshed:
            self.refresh()

    def refresh(self):
        d = self._refresh()
        d.addErrback(lambda x: None)

    @twisted.internet.defer.inlineCallbacks
    def _refresh(self):
        self.pid.busy()
        try:
            for n in self.regs:
                if n == 'flags':
                    yield self.pid.flags()
                else:
                    yield self.pid.holding_read(n)
            self.refreshed = True
        finally:
            self.pid.unbusy()

class PID(Gtk.TreeView):
    def __init__(self, pid):
        self.pid = pid
        self.refreshed = False
        self.store = Gtk.ListStore(int, str, int, int)
        Gtk.TreeView.__init__(self, self.store)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Group", renderer, text=0)
        self.append_column(column)

        reg = registers['P1']
        adj = Gtk.Adjustment(reg[3], reg[2][0], reg[2][1], reg[4])
        renderer = Gtk.CellRendererSpin()
        renderer.set_property("editable", True)
        renderer.set_property("adjustment", adj)
        renderer.set_property("digits", 1)
        renderer.connect('edited', self.on_p_edited)
        column = Gtk.TreeViewColumn("P                              ", renderer, text=1)
        self.append_column(column)

        reg = registers['I1']
        adj = Gtk.Adjustment(reg[3], reg[2][0], reg[2][1], reg[4])
        renderer = Gtk.CellRendererSpin()
        renderer.set_property("editable", True)
        renderer.set_property("adjustment", adj)
        renderer.set_property("width-chars", 20)
        renderer.connect('edited', self.on_i_edited)
        column = Gtk.TreeViewColumn("I                              ", renderer, text=2)
        self.append_column(column)

        reg = registers['d1']
        adj = Gtk.Adjustment(reg[3], reg[2][0], reg[2][1], reg[4])
        renderer = Gtk.CellRendererSpin()
        renderer.set_property("editable", True)
        renderer.set_property("adjustment", adj)
        renderer.connect('edited', self.on_d_edited)
        column = Gtk.TreeViewColumn("d                              ", renderer, text=3)
        self.append_column(column)

        for i in range(1,10):
            self.store.append([i, '0.1', 0, 0])

        self.popup = Gtk.Menu()
        item = Gtk.MenuItem('Load from work tab')
        item.connect('activate', self.on_load)
        self.popup.append(item)
        item = Gtk.MenuItem('Export to work tab')
        item.connect('activate', self.on_export)
        self.popup.append(item)

        pid.connect('changed', self.changed)
        self.connect('button-release-event', self.on_button)

    def on_p_edited(self, widget, path, text):
        n = 'P'+(str(int(path) + 1))
        try:
            d = self.pid.raw(n, float(text))
            d.addErrback(lambda x: None)
        except:
            pass

    def on_i_edited(self, widget, path, text):
        n = 'I'+(str(int(path) + 1))
        try:
            d = self.pid.raw(n, int(text))
            d.addErrback(lambda x: None)
        except:
            pass

    def on_d_edited(self, widget, path, text):
        n = 'd'+(str(int(path) + 1))
        try:
            d = self.pid.raw(n, int(text))
            d.addErrback(lambda x: None)
        except:
            pass

    def on_button(self, widget, event):
        if event.button != 3:
            return

        path_info = self.get_path_at_pos(event.x, event.y)
        if path_info is None:
            return

        self.click_path, col, x, y = path_info
        self.grab_focus()
        self.set_cursor(self.click_path, None)
        self.popup.popup(None, None, None, None, event.button, event.time)
        self.popup.show_all()
        return True

    def on_load(self, widget):
        d = self.do_load(self.click_path)
        d.addErrback(lambda x: None)

    @twisted.internet.defer.inlineCallbacks
    def do_load(self, path):
        self.pid.busy()
        try:
            row = str(int(str(path)) + 1)
            for i in 'PId':
                val, mult = yield self.pid.holding_read(i)
                yield self.pid.raw(i + row, val)
        finally:
            self.pid.unbusy()

    def on_export(self, widget):
        d = self.do_export(self.click_path)

    @twisted.internet.defer.inlineCallbacks
    def do_export(self, path):
        self.pid.busy()
        try:
            row = str(int(str(path)) + 1)
            for i in 'PId':
                val, mult = yield self.pid.holding_read(i + row)
                yield self.pid.raw(i, val)
        finally:
            self.pid.unbusy()

    def changed(self, pid, n, val, mult):
        if len(n) != 2 or n[0] not in "PId" or n[1] not in "123456789":
            return
        path = str(int(n[1]) - 1)
        treeiter = self.store.get_iter(path)
        col = '_PId'.index(n[0])
        if n[0] == 'P':
            val = '%.1f' % (0.1 if val is None else val)
        else:
            val = 0 if val is None else val
        self.store.set(treeiter, col, val)

    def on_show(self):
        if not self.refreshed:
            self.refresh()

    def refresh(self):
        d = self._refresh()
        d.addErrback(lambda x: None)

    @twisted.internet.defer.inlineCallbacks
    def _refresh(self):
        self.pid.busy()
        try:
            for row in range(1,10):
                self.set_cursor(str(row-1), None)
                for col in "PId":
                    yield self.pid.holding_read(col + str(row))
            self.set_cursor("0", None)
            self.refreshed = True
        finally:
            self.pid.unbusy()

class Ramp_soak(Gtk.ScrolledWindow):
    def __init__(self, pid):
        self.pid = pid
        self.refreshed = False
        self.store = Gtk.ListStore(int, int, str, int, int)
        self.tree = Gtk.TreeView(self.store)
        Gtk.ScrolledWindow.__init__(self)

        renderer = Gtk.CellRendererText()
        column = Gtk.TreeViewColumn("Step", renderer, text=0)
        self.tree.append_column(column)

        reg = registers['C-01']
        adj = Gtk.Adjustment(reg[3]+1, reg[2][0]+1, reg[2][1]+1, reg[4])
        renderer = Gtk.CellRendererSpin()
        renderer.set_property("editable", True)
        renderer.set_property("adjustment", adj)
        renderer.connect('edited', self.on_group_edited)
        column = Gtk.TreeViewColumn("PID Group", renderer, text=1)
        self.tree.append_column(column)

        mode_store = Gtk.ListStore(str)
        for mode in run_modes.keys():
            mode_store.append([mode])

        renderer = Gtk.CellRendererCombo()
        renderer.set_property("editable", True)
        renderer.set_property("model", mode_store)
        renderer.set_property("has-entry", False)
        renderer.set_property("text-column", 0)
        renderer.connect('edited', self.on_mode_edited)
        column = Gtk.TreeViewColumn("Mode", renderer, text=2)
        self.tree.append_column(column)

        reg = registers['t-01']
        adj = Gtk.Adjustment(1, reg[2]['Run'][0], reg[2]['Run'][1], reg[4])
        renderer = Gtk.CellRendererSpin()
        renderer.set_property("editable", True)
        renderer.set_property("adjustment", adj)
        renderer.connect('edited', self.on_time_edited)
        column = Gtk.TreeViewColumn("Runtime/Jump to", renderer, text=3)
        self.tree.append_column(column)

        reg = registers['Sv01']
        adj = Gtk.Adjustment(reg[3], reg[2][0], reg[2][1], reg[4])
        renderer = Gtk.CellRendererSpin()
        renderer.set_property("editable", True)
        renderer.set_property("adjustment", adj)
        renderer.connect('edited', self.on_sv_edited)
        column = Gtk.TreeViewColumn("Set Value", renderer, text=4)
        self.tree.append_column(column)

        for i in range(1,65):
            self.store.append([i, 1, 'Pause', 1, 0])

        self.add(self.tree)
        pid.connect('changed', self.changed)

    def on_group_edited(self, widget, path, text):
        n = 'C-%02d' % (int(str(path)) + 1)
        d = self.pid.raw(n, int(text)-1)
        d.addErrback(lambda x: None)

    def on_mode_edited(self, widget, path, text):
        n = 't-%02d' % (int(str(path)) + 1)
        if text == 'Jump' or text == 'Run':
            treeiter = self.store.get_iter(path)
            idx = self.store.get(treeiter, 3)[0]
            if text == 'Jump':
                if not 1 <= idx <= 64:
                    idx = 1
                idx = -idx
            text = (text, idx)
        d = self.pid.raw(n, text)
        d.addErrback(lambda x: None)

    def on_time_edited(self, widget, path, text):
        n = 't-%02d' % (int(str(path)) + 1)
        treeiter = self.store.get_iter(path)
        mode = self.store.get(treeiter, 2)[0]
        val = int(text)
        if mode == 'Jump':
            if not 1 <= val <= 64:
                return
            val = -val
        elif mode == 'Run':
            pass
        else:
            return
        d = self.pid.raw(n, (mode, val))
        d.addErrback(lambda x: None)

    def on_sv_edited(self, widget, path, text):
        n = 'Sv%02d' % (int(str(path)) + 1)
        d = self.pid.raw(n, int(text))
        d.addErrback(lambda x: None)

    def changed(self, pid, n, val, mult):
        if len(n) != 4:
            return
        if n[0] in "Ct":
            if n[1] != '-':
                return
        elif n[0:2] == 'Sv':
            pass
        else:
            return
        if n[2] not in "0123456789" or n[3] not in "0123456789":
            return

        path = str(int(n[2:4]) - 1)
        treeiter = self.store.get_iter(path)
        if n[0] == 'C':
            val = 0 if val is None else val
            self.store.set(treeiter, 1, val+1)
        elif n[0] == 't':
            idx = None
            if type(val) is tuple:
                val, idx = val
            if val == 'Run':
                self.store.set(treeiter, 3, idx)
            elif val == 'Jump':
                self.store.set(treeiter, 3, abs(idx))
            self.store.set(treeiter, 2, val)
        else:
            val = 0 if val is None else val
            self.store.set(treeiter, 4, int(val))

    def on_show(self):
        if not self.refreshed:
            self.refresh()

    def refresh(self):
        d = self._refresh()
        d.addErrback(lambda x: None)

    @twisted.internet.defer.inlineCallbacks
    def _refresh(self):
        self.pid.busy()
        try:
            for row in range(1,65):
                self.tree.set_cursor(str(row-1), None)
                for col in [ "C-", "t-", "Sv" ]:
                    yield self.pid.holding_read(col + ('%02d' % row))
            self.tree.set_cursor("0", None)
            self.refreshed = True
        finally:
            self.pid.unbusy()

class ATWindow(Gtk.Window):
    def __init__(self, pid):
        Gtk.Window.__init__(self, title="Auto-tune")
        self.pid = pid
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        f = matplotlib.figure.Figure()
        self.axes = f.add_subplot(111)
        self.axes.set_xlabel('Time (sec.)')
        self.axes.set_ylabel('Temperature (C)')
        self.axes.autoscale()
        self.out_axes = self.axes.twinx()
        self.out_axes.set_ylabel('OUT (%)')
        self.out_axes.autoscale()
        #self.axes.set_xlim(0, 5*60)
        #self.axes.set_ylim(20, 300)
        self.axes.grid()
        #self.axes.xaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(self.format_xaxis))
        self.pv_x = []
        self.pv_y = []
        self.sv_x = []
        self.sv_y = []
        self.out_x = []
        self.out_y = []
        self.pv_plot, = self.axes.plot(self.pv_x, self.pv_y, 'b--') #b
        self.sv_plot, = self.axes.plot(self.sv_x, self.sv_y, 'k-') #k
        self.out_plot, = self.out_axes.plot(self.out_x, self.out_y, 'r:') #r

        self.canvas = FigureCanvas(f)
        self.canvas.set_size_request(800,600)

        vbox.add(self.canvas)

        hbox = Gtk.Box()
        button = Gtk.Button('Cancel', Gtk.STOCK_CANCEL)
        button.connect('clicked', self.on_cancel)
        hbox.add(button)
        vbox.add(hbox)

        self.add(vbox)
        self.run = True
        self.d = self.loop()
        self.d.addErrback(lambda x: None)
        self.connect('delete-event', self.on_delete)

    def on_delete(self, widget, event):
        self.run = False

    def on_cancel(self, widget):
        self.emit('delete-event', None)
        self.destroy()

    @twisted.internet.defer.inlineCallbacks
    def loop(self):
        self.pid.busy()
        try:
            d = self.pid.raw('NAT', 0)
            d.addErrback(lambda x: None)
            yield d
            yield self.pid.raw('ModL', 'SV')
            start = time.time()
            yield self.pid.raw('At', 'On')
            while self.run:
                #active = yield self.pid.flags()['AT']
                #if not active:
                #    print 'done'
                #    break

                pv, mult = yield self.pid.holding_read('PV')
                self.pv_x.append(time.time() - start)
                self.pv_y.append(pv)
                self.pv_plot.set_data(self.pv_x, self.pv_y)
                self.axes.relim()
                self.axes.autoscale()
                self.canvas.draw()

                sv, mult = yield self.pid.holding_read('dSV')
                self.sv_x.append(time.time() - start)
                self.sv_y.append(sv)
                self.sv_plot.set_data(self.sv_x, self.sv_y)
                self.axes.relim()
                self.axes.autoscale()
                self.canvas.draw()

                out, mult = yield self.pid.holding_read('OUT')
                self.out_x.append(time.time() - start)
                self.out_y.append(out)
                self.out_plot.set_data(self.out_x, self.out_y)
                self.out_axes.relim()
                self.out_axes.autoscale()
                self.canvas.draw()

                d = twisted.internet.defer.Deferred()
                twisted.internet.reactor.callLater(1, d.callback, None)
                yield d
                print 'dot'
        finally:
            d = self.pid.raw('NAT', 0)
            d.addErrback(lambda x: None)
            yield d
            self.pid.unbusy()


UI_INFO = """
<ui>
  <menubar name='MenuBar'>
    <menu action='FileMenu'>
      <menuitem action='FileQuit' />
    </menu>
    <menu action='ActionMenu'>
      <menuitem action='ActionAT' />
    </menu>
  </menubar>
</ui>
"""

class PIDWindow(Gtk.Window):
    def __init__(self, pid):
        Gtk.Window.__init__(self, title="PID")

        action_group = Gtk.ActionGroup("profile_actions")
        action_group.add_actions([
            ("FileMenu", None, "File", None, None, None),
            ("FileQuit", Gtk.STOCK_QUIT, "_Quit", "<control>Q", None, Gtk.main_quit),
            ("ActionMenu", None, "Action", None, None, None),
            ("ActionAT", None, "Auto-tune", None, None, self.on_at)
        ])

        uimanager = Gtk.UIManager()
        uimanager.add_ui_from_string(UI_INFO)
        accelgroup = uimanager.get_accel_group()
        self.add_accel_group(accelgroup)
        uimanager.insert_action_group(action_group)
        menubar = uimanager.get_widget("/MenuBar")

        self.pid = pid
        pid.connect('process-start', lambda x: self.set_sensitive(False))
        pid.connect('process-end', lambda x: self.set_sensitive(True))
        self.notebook = Gtk.Notebook()
        self.notebook.append_page(Function(pid), Gtk.Label("Function"))
        self.notebook.append_page(Work(pid), Gtk.Label("Work"))
        self.notebook.append_page(Control(pid), Gtk.Label("Control"))
        self.notebook.append_page(Status(pid), Gtk.Label("Status"))
        self.notebook.append_page(PID(pid), Gtk.Label("PID"))
        self.notebook.append_page(Ramp_soak(pid), Gtk.Label("Ramp/soak"))
        self.notebook.connect('switch-page', self.on_select_page)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        vbox.pack_start(menubar, False, False, 0)
        vbox.add(self.notebook)
        hbox = Gtk.Box()
        button = Gtk.Button('Refresh', Gtk.STOCK_REFRESH)
        button.connect('clicked', self.refresh)
        hbox.add(button)
        vbox.add(hbox)
        self.add(vbox)

    def on_at(self, widget):
        win = ATWindow(self.pid)
        win.show_all()

    def refresh(self, button):
        self.notebook.get_nth_page(self.notebook.get_current_page()).refresh()

    def on_select_page(self, notebook, page, page_num):
        page.on_show()

def main():
    port = SerialModbusClient("/dev/ttyUSB0", twisted.internet.reactor, timeout=0.1)
    win = PIDWindow(port.protocol)
    win.connect('delete-event', Gtk.main_quit)

    win.show_all()
    twisted.internet.reactor.run()

if __name__ == '__main__':
    main()

