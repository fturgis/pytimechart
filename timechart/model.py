# timechart project
# the timechart model with all loading facilities

from numpy import amin, amax, arange, searchsorted, sin, pi, linspace
import numpy as np

from enthought.traits.api import HasTraits, Instance, Str, Float,Delegate,\
    DelegatesTo, Int, Long, Enum, Color, List, Bool, CArray, Property, cached_property, String, Button
from enthought.traits.ui.api import Group, HGroup, Item, View, spring, Handler,VGroup,TableEditor
from enthought.enable.colors import ColorTrait

from timechart import colors
from timechart.process_table import process_table_editor

import numpy
import sys 

def _pretty_time(time):
    if time > 1000000:
        time = time/1000000.
        return "%.1f s"%(time)
    if time > 1000:
        time = time/1000.
        return "%.1f ms"%(time)
    return "%.1f us"%(time)

class tcGeneric(HasTraits):
    name = String
    start_ts = CArray 
    end_ts = CArray 
    types = CArray 
    has_comments = Bool(True)
    total_time = Property(Int)
    max_types = Property(Int)
    max_latency = Property(Int)
    max_latency_ts = Property(CArray)
    
    @cached_property
    def _get_total_time(self):
        return sum(self.end_ts-self.start_ts)
    @cached_property
    def _get_max_types(self):
        return amax(self.types)
    @cached_property
    def _get_max_latency(self):
        return -1

    def get_partial_tables(self,start,end):
        low_i = searchsorted(self.end_ts,start)
        high_i = searchsorted(self.start_ts,end)
        ends = self.end_ts[low_i:high_i].copy()
        starts = self.start_ts[low_i:high_i].copy()
        if len(starts)==0:
            return np.array([]),np.array([]),[]
        # take care of activities crossing the selection
        if starts[0]<start:
            starts[0] = start
        if ends[-1]>end:
            ends[-1] = end
        types = self.types[low_i:high_i]
        return starts,ends,types

    # UI traits
    default_bg_color = Property(ColorTrait)
    bg_color = Property(ColorTrait)
    @cached_property
    def _get_bg_color(self):
        return colors.get_traits_color_by_name("idle_bg")

class tcIdleState(tcGeneric):
    def get_comment(self,i):
        return colors.get_colorname_by_id(self.types[i])
class tcFrequencyState(tcGeneric):
    def get_comment(self,i):
        return "%d"%(self.types[i])

class tcProcess(tcGeneric):
    name = Property(String) # overide TimeChart
    # start_ts=CArray # inherited from TimeChart
    # end_ts=CArray # inherited from TimeChart
    # values = CArray   # inherited from TimeChart
    pid = Long
    ppid = Long
    selection_time = Long(0)
    selection_pc = Float(0)
    comm = String
    cpus = CArray
    comments = CArray
    has_comments = Bool(True)
    show = Bool(True)
    process_type = String
    project = None
    @cached_property
    def _get_name(self):
        if self.process_type=="runtime_pm":
            return "%s:%d"%(self.comm,self.pid)
        return "%s:%d (%s)"%(self.comm,self.pid, _pretty_time(self.total_time))

    def get_comment(self,i):
        if self.process_type=="runtime_pm":
            return colors.get_colorname_by_id(self.types[i])[len("rpm_"):]
        elif len(self.comments)>i:
            return "%d"%(self.comments[i])
        elif len(self.cpus)>i:
            return "%d"%(self.cpus[i])
        else:
            return ""
    @cached_property
    def _get_max_latency(self):
        if self.pid==0 and self.comm.startswith("irq"):
            return 1000

    @cached_property
    def _get_max_latency_ts(self):
        if self.max_latency > 0:
            indices = np.nonzero((self.end_ts - self.start_ts) > self.max_latency)[0]
            return np.array(sorted(map(lambda i:self.start_ts[i], indices)))
        return []

    @cached_property
    def _get_default_bg_color(self):
        if self.max_latency >0 and max(self.end_ts - self.start_ts)>self.max_latency:
            return (1,.1,.1,1)
        return colors.get_traits_color_by_name(self.process_type+"_bg")

    def _get_bg_color(self):
        if self.project != None and self in self.project.selected:
            return  colors.get_traits_color_by_name("selected_bg")
        return self.default_bg_color


class tcProject(HasTraits):
    c_states = List(tcGeneric)
    p_states = List(tcGeneric)
    processes = List(tcProcess)
    selected =  List(tcProcess)
    show = Button()
    hide = Button()
    selectall = Button()
    filename = Str("")
    power_event = CArray
    num_cpu = Property(Int,depends_on='c_states')
    num_process = Property(Int,depends_on='process')
    traits_view = View( 
        HGroup(Item('show'), Item('hide') ,Item('selectall',label='all'),show_labels  = False),
        Item( 'processes',
              show_label  = False,
              height=40,
              editor      = process_table_editor
              )
        )
    first_ts = 0
    def _show_changed(self):
        for i in self.selected:
            i.show = True
    def _hide_changed(self):
        for i in self.selected:
            i.show = False
    def _selectall_changed(self):
        if self.selected == self.processes:
            self.selected = []
        else:
            self.selected = self.processes

    @cached_property
    def _get_num_cpu(self):
        return len(self.c_states)
    def _get_num_process(self):
        return len(self.processes)
    def process_list_selected(self, selection):
        print selection
    def load(self,filename):
        self.filename = filename
        if filename.endswith(".tmct"):
            return self.load_tmct(filename)
        else:
            return self.load_ftrace(filename)
######### stats part ##########

    def c_states_stats(self,start,end):
        l = []
        for tc in self.c_states: # walk cstates per cpus
            starts,ends,types = tc.get_partial_tables(start,end)
            stats = {}
            tot = 0
            for t in np.unique(types):
                inds = np.where(types==t)
                time = sum(ends[inds]-starts[inds])
                tot += time
                stats[t] = time
            stats[0] = (end-start)-tot
            l.append(stats)  
        return l
    def process_stats(self,start,end):
        fact = 100./(end-start)
        for tc in self.processes:
            starts,ends,types = tc.get_partial_tables(start,end)
            #@todo, need to take care of running vs waiting
            inds = np.where(types==1)
            tot = sum(ends[inds]-starts[inds])
            tc.selection_time = int(tot)
            tc.selection_pc = tot*fact
    def get_selection_text(self,start,end):
        low_line = -1
        high_line = -1
        for tc in self.processes:
            low_i = searchsorted(tc.end_ts,start)
            high_i = searchsorted(tc.start_ts,end)
            if low_i < len(tc.linenumbers):
                ll = tc.linenumbers[low_i]
                if low_line==-1 or low_line > ll:
                    low_line = ll
            if high_i < len(tc.linenumbers):
                hl = tc.linenumbers[high_i]
                if high_line==-1 or high_line > hl:
                    high_line = hl
        return self.get_partial_text(self.filename, low_line, high_line)

######### generic parsing part ##########


    def generic_find_process(self,pid,comm,ptype):
        if self.tmp_process.has_key((pid,comm)):
            return self.tmp_process[(pid,comm)]
        tmp = {'type':ptype,'comm':comm,'pid':pid,'start_ts':[],'end_ts':[],'types':[],'cpus':[],'comments':[]}
        if not (pid==0 and comm =="swapper"):
            self.tmp_process[(pid,comm)] = tmp
        return tmp

    def generic_process_start(self,process,event, build_p_stack=True):
        if process['comm']=='swapper' and process['pid']==0:
            return # ignore swapper event
        if len(process['start_ts'])>len(process['end_ts']):
            process['end_ts'].append(event.timestamp)
        if self.first_ts == 0:
            self.first_ts = event.timestamp
        self.cur_process_by_pid[process['pid']] = process
        if build_p_stack :
            p_stack = self.cur_process[event.common_cpu]
            if p_stack:
                p = p_stack[-1]
                if len(p['start_ts'])>len(p['end_ts']):
                    p['end_ts'].append(event.timestamp)
                # mark old process to wait for cpu 
                p['start_ts'].append(int(event.timestamp))
                p['types'].append(colors.get_color_id("waiting_for_cpu")) 
                p['cpus'].append(event.common_cpu)
                p_stack.append(process)
            else:
                self.cur_process[event.common_cpu] = [process]
        # mark process to use cpu
        process['start_ts'].append(event.timestamp)
        process['types'].append(colors.get_color_id("running"))
        process['cpus'].append(event.common_cpu)

    def generic_process_end(self,process,event, build_p_stack=True):
        if process['comm']=='swapper' and process['pid']==0:
            return # ignore swapper event
        if len(process['start_ts'])>len(process['end_ts']):
            process['end_ts'].append(event.timestamp)
        if build_p_stack :
            p_stack = self.cur_process[event.common_cpu]
            if p_stack:
                p = p_stack.pop()
                if p['pid'] != process['pid']:
                    print  "warning: process premption stack following failure on CPU",event.common_cpu, p['comm'],p['pid'],process['comm'],process['pid'],map(lambda a:"%s:%d"%(a['comm'],a['pid']),p_stack),event.linenumber
                    p_stack = []
                elif p['comm'] != process['comm']:
                    # this is the fork and exec case.
                    # fix the temporary process that had the comm of the parent
                    # remove old pid,comm from process list
                    del self.tmp_process[(p['pid'],p['comm'])]
                    # add new pid,comm to process list
                    p['comm'] = process['comm']
                    self.tmp_process[(p['pid'],p['comm'])] = p
                    if len(p['start_ts'])>len(p['end_ts']):
                        p['end_ts'].append(event.timestamp)
                    
                if p_stack:
                    p = p_stack[-1]
                    if len(p['start_ts'])>len(p['end_ts']):
                        p['end_ts'].append(event.timestamp)
                    # mark old process to run on cpu 
                    p['start_ts'].append(event.timestamp)
                    p['types'].append(colors.get_color_id("running"))
                    p['cpus'].append(event.common_cpu)
        
    def do_event_sched_switch(self,event):
        prev = self.generic_find_process(event.prev_pid,event.prev_comm,"user_process")
        next = self.generic_find_process(event.next_pid,event.next_comm,"user_process")

        self.generic_process_end(prev,event)

        if event.__dict__.has_key('prev_state') and event.prev_state == 'R':# mark prev to be waiting for cpu
            prev['start_ts'].append(event.timestamp)
            prev['types'].append(colors.get_color_id("waiting_for_cpu"))
            prev['cpus'].append(event.common_cpu)

        self.generic_process_start(next,event)
        
    def do_event_sched_wakeup(self,event):
        p_stack = self.cur_process[event.common_cpu]
        if p_stack:
            p = p_stack[-1]
            self.wake_events.append(((p['comm'],p['pid']),(event.comm,event.pid),event.timestamp))
        else:
            self.wake_events.append(((event.common_comm,event.common_pid),(event.comm,event.pid),event.timestamp))
    def do_event_irq_handler_entry(self,event,soft=""):
        process = self.generic_find_process(0,"%sirq%d:%s"%(soft,event.irq,event.name),soft+"irq")
        self.last_irq[(event.irq,soft)] = process
        self.generic_process_start(process,event)
    def do_event_irq_handler_exit(self,event,soft=""):
        try:
            process = self.last_irq[(event.irq,soft)]
        except KeyError:
            print "error did not find last irq"
            print self.last_irq.keys(),(event.irq,soft)
            return
        self.generic_process_end(process,event)
        try:
            if event.ret=="unhandled":
                process['types'][-1]=4
	except:
	    pass
    def do_event_softirq_entry(self,event):
        event.irq = event.vec
        event.name = ""
        return self.do_event_irq_handler_entry(event,"soft")
    def do_event_softirq_exit(self,event):
        event.irq = event.vec
        event.name = ""
        return self.do_event_irq_handler_exit(event,"soft")
        
    def do_event_spi_sync(self,event):
        process = self.generic_find_process(0,"spi:%s"%(event.caller),"spi")
        self.last_spi.append(process)
        self.generic_process_start(process,event,False)
    def do_event_spi_complete(self,event):
        process = self.last_spi.pop(0)
        self.generic_process_end(process,event,False)
    def do_event_spi_async(self,event):
        if event.caller != 'spi_sync':
            self.do_event_spi_sync(event,False)

    def do_event_wakelock_lock(self,event):
        process = self.generic_find_process(0,"wakelock:%s"%(event.name),"wakelock")
        self.generic_process_start(process,event,False)
        self.wake_events.append(((event.common_comm,event.common_pid),(process['comm'],process['pid']),event.timestamp))

    def do_event_wakelock_unlock(self,event):
        process = self.generic_find_process(0,"wakelock:%s"%(event.name),"wakelock")
        self.generic_process_end(process,event,False)
        self.wake_events.append(((event.common_comm,event.common_pid),(process['comm'],process['pid']),event.timestamp))

    def do_event_workqueue_execution(self,event):
        process = self.generic_find_process(0,"work:%s"%(event.func),"work")
        self.generic_process_start(process,event)
        self.generic_process_end(process,event)
        
    def do_event_power_frequency(self,event):
        self.ensure_cpu_allocated(event.common_cpu)
        if event.type==2:# p_state
            tc = self.tmp_p_states[event.common_cpu]
            tc['start_ts'].append(event.timestamp)
            tc['types'].append(event.state)

    def do_event_power_start(self,event):
        self.ensure_cpu_allocated(event.common_cpu)
        if event.type==1:# c_state
            tc = self.tmp_c_states[event.common_cpu]
            if len(tc['start_ts'])>len(tc['end_ts']):
                tc['end_ts'].append(event.timestamp)
                self.missed_power_end +=1
                if self.missed_power_end < 10:
                    print "warning: missed power_end"
                if self.missed_power_end == 10:
                    print "warning: missed power_end: wont warn anymore!"
                    
            tc['start_ts'].append(event.timestamp)
            tc['types'].append(colors.get_color_id("C%d"%(event.state)))

    def do_event_power_end(self,event):
        self.ensure_cpu_allocated(event.common_cpu)

        tc = self.tmp_c_states[event.common_cpu]
        if len(tc['start_ts'])>len(tc['end_ts']):
            tc['end_ts'].append(event.timestamp)

    def do_event_runtime_pm_status(self,event):
        if self.first_ts == 0:
            self.first_ts = event.timestamp-1

        p = self.generic_find_process(0,"runtime_pm:%s %s"%(event.driver,event.dev),"runtime_pm")
        if len(p['start_ts'])>len(p['end_ts']):
            p['end_ts'].append(event.timestamp)
        if event.status!="SUSPENDED":
            p['start_ts'].append(int(event.timestamp))
            p['types'].append(colors.get_color_id("rpm_%s"%(event.status.lower())))
            p['cpus'].append(event.common_cpu)

    def do_event_runtime_pm_usage(self,event):
        p = self.generic_find_process(0,"runtime_pm_usage:%s %s"%(event.driver,event.dev),"runtime_pm")
        if len(p['start_ts'])>len(p['end_ts']):
            p['end_ts'].append(event.timestamp)
        if event.usage!=0:
            p['start_ts'].append(int(event.timestamp))
            p['types'].append(colors.get_color_id("rpm_usage=%d"%(event.usage)))
            p['cpus'].append(event.common_cpu)


    def do_function_default(self,event):
        process = self.generic_find_process(0,"kernel function:%s"%(event.callee),"function")
        self.generic_process_start(process,event)
        self.generic_process_end(process,event)

    def do_event_default(self,event):
        process = self.generic_find_process(0,"event:%s"%(event.event),"event")
        self.generic_process_start(process,event)
        self.generic_process_end(process,event)


    def start_parsing(self):
        # we build our data into python data formats, who are resizeable
        # once everything is parsed, we will transform it into numpy array, for fast access
        self.tmp_c_states = []
        self.tmp_p_states = []
        self.tmp_process = {}
        self.cur_process_by_pid = {}
        self.wake_events = []
        self.cur_process = [None]*20
        self.last_irq={}
        self.last_spi=[]
        self.missed_power_end = 0
        self.methods = {}
        for name in dir(self):
            method = getattr(self, name)
            if callable(method):
                self.methods[name] = method

    def finish_parsing(self):
        #put generated data in unresizable numpy format
        c_states = []
        i=0
        for tc in self.tmp_c_states:
            t = tcIdleState(name='cpu%d'%(i))
            while len(tc['start_ts'])>len(tc['end_ts']):
                tc['end_ts'].append(tc['start_ts'][-1])
            t.start_ts = numpy.array(tc['start_ts'])
            t.end_ts = numpy.array(tc['end_ts'])
            t.types = numpy.array(tc['types'])
            c_states.append(t)
            i+=1
        self.c_states=c_states
        i=0
        p_states = []
        for tc in self.tmp_p_states:
            t = tcFrequencyState(name='cpu%d'%(i))
            t.start_ts = numpy.array(tc['start_ts'])
            t.end_ts = numpy.array(tc['end_ts'])
            t.types = numpy.array(tc['types'])
            i+=1
            p_states.append(t)
        self.wake_events = numpy.array(self.wake_events,dtype=[('waker',tuple),('wakee',tuple),('time','uint64')])
        self.p_states=p_states
        processes = []
        last_ts = 0
        for pid,comm in self.tmp_process:
            tc = self.tmp_process[pid,comm]
            if len(tc['end_ts'])>0 and last_ts < tc['end_ts'][-1]:
                last_ts = tc['end_ts'][-1]
        for pid,comm in self.tmp_process:
            t = tcProcess(pid=pid,comm=comm,project=self)
            tc = self.tmp_process[pid,comm]
            while len(tc['start_ts'])>len(tc['end_ts']):
                tc['end_ts'].append(last_ts)
            t.start_ts = numpy.array(tc['start_ts'])
            t.end_ts = numpy.array(tc['end_ts'])
            t.types = numpy.array(tc['types'])
            t.cpus = numpy.array(tc['cpus'])
            t.comments = numpy.array(tc['comments'])
            t.process_type = tc["type"]
            processes.append(t)
        def cmp_process(x,y):
            # sort process by type, pid, comm
            def type_index(t):
                order = ["runtime_pm","wakelock","irq","softirq","work",
                         "function","event","spi","kernel_process","user_process"]
                try:
                    return order.index(t)
                except ValueError:
                    return len(order)+1
            c = cmp(type_index(x.process_type),type_index(y.process_type))
            if c != 0:
                return c
            c = cmp(x.pid,y.pid)
            if c != 0:
                return c
            c = cmp(x.comm,y.comm)
            return c

        processes.sort(cmp_process)
        self.processes = processes
        self.p_states=p_states
        self.tmp_c_states = []
        self.tmp_p_states = []
        self.tmp_process = {}

    def ensure_cpu_allocated(self,cpu):
        # ensure we have enough per_cpu p/s_states timecharts
        while len(self.tmp_c_states)<=cpu:
            self.tmp_c_states.append({'start_ts':[],'end_ts':[],'types':[]})
        while len(self.tmp_p_states)<=cpu:
            self.tmp_p_states.append({'start_ts':[],'end_ts':[],'types':[]})
                                     
    def handle_trace_event(self,event):
        callback = "do_event_"+event.event
        if event.event=='function':
            callback = "do_event_"+event.callee
        if self.methods.has_key(callback):
            self.methods[callback](event)
        elif event.event=='function':
            self.do_function_default(event)
        else:
            self.do_event_default(event)

