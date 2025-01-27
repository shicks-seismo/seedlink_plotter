#!/usr/bin/env python
from __future__ import print_function

import matplotlib
# Set the backend for matplotlib.
matplotlib.use("TkAgg")
matplotlib.rc('figure.subplot', hspace=0)
matplotlib.rc('font', family="monospace")
import tkinter

from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.ticker import MaxNLocator
from matplotlib.patheffects import withStroke
from matplotlib.dates import date2num
import matplotlib.pyplot as plt
from obspy import Stream, Trace
from obspy import __version__ as OBSPY_VERSION
from obspy.core import UTCDateTime
from obspy.core.event import Catalog
from obspy.core.util import MATPLOTLIB_VERSION
from argparse import ArgumentParser,ArgumentDefaultsHelpFormatter
from math import sin
import threading
import time
import warnings
import os
import sys
from urllib.request import URLError
import logging
import numpy as np


range_func = range
input_func = input


OBSPY_VERSION = [int(x) for x in OBSPY_VERSION.split(".")[:2]]
# check obspy version and warn if it's below 0.10.0, which means that a memory
# leak is present in the used seedlink client (unless working on some master
# branch version after obspy/obspy@5ce975c3710ca, which is impossible to check
# reliably). see #7 and obspy/obspy#918.
# imports depend of the obspy version
if OBSPY_VERSION < [0, 10]:
    warning_msg = (
        "ObsPy version < 0.10.0 has a memory leak in SeedLink Client. "
        "Please update your ObsPy installation to avoid being affected by "
        "the memory leak (see "
        "https://github.com/bonaime/seedlink_plotter/issues/7).")
    warnings.warn(warning_msg)
    sys.exit()

from obspy.clients.seedlink.slpacket import SLPacket
from obspy.clients.seedlink import SLClient
from obspy.clients.fdsn import Client

# Compatibility checks
# UTCDateTime
try:
    UTCDateTime.format_seedlink
except AttributeError:
    # create the new format_seedlink fonction using the old formatSeedLink
    # method
    def format_seedlink(self):
        return self.formatSeedLink()
    # add the function in the class
    setattr(UTCDateTime, 'format_seedlink', format_seedlink)
# SLPacket
try:
    SLPacket.get_type
except AttributeError:
  # create the new get_type fonction using the old getType method
    def get_type(self):
        return self.getType()
    # add the function in the class
    setattr(SLPacket, 'get_type', get_type)

try:
    SLPacket.get_trace
except AttributeError:
  # create the new get_trace fonction using the old getTrace method
    def get_trace(self):
        return self.getTrace()
    # add the function in the class
    setattr(SLPacket, 'get_trace', get_trace)


class SeedlinkPlotter(tkinter.Tk):

    """
    This module plots realtime seismic data from a Seedlink server
    """

    def __init__(self, stream=None, events=None, myargs=None, lock=None,
                 drum_plot=True, trace_ids=None, *args, **kwargs):
        tkinter.Tk.__init__(self, *args, **kwargs)
        favicon = tkinter.PhotoImage(
            file=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "favicon.gif"))
        self.tk.call('wm', 'iconphoto', self._w, favicon)
        self.wm_title("seedlink-plotter {}".format(myargs.seedlink_server))
        self.focus_set()
        self._bind_keys()
        args = myargs
        self.lock = lock
        ### size and position
        self.geometry(str(args.x_size) + 'x' + str(args.y_size) + '+' + str(
            args.x_position) + '+' + str(args.y_position))
        w, h, pad = self.winfo_screenwidth(), self.winfo_screenheight(), 3
        self._geometry = ("%ix%i+0+0" % (w - pad, h - pad))
        # hide the window decoration
        if args.without_decoration:
            self.wm_overrideredirect(True)
        if args.fullscreen:
            self._toggle_fullscreen(None)

        # main figure
        self.figure = Figure()
        canvas = FigureCanvasTkAgg(self.figure, master=self)

        if MATPLOTLIB_VERSION[:2] >= [2, 2]:
            canvas.draw()
        else:
            canvas.show()
        canvas.get_tk_widget().pack(fill=tkinter.BOTH, expand=1)

        self.backtrace = args.backtrace_time
        self.canvas = canvas
        self.scale = args.scale
        self.args = args
        self.stream = stream
        self.events = events
        self.drum_plot = drum_plot
        self.ids = trace_ids

        # Colors
        if args.rainbow:
            # Rainbow colors !
            self.color = self.rainbow_color_generator(
                int(args.nb_rainbow_colors))
        else:
            # Regular colors: Black, Red, Blue, Green
            self.color = ('#000000', '#e50000', '#0000e5', '#448630')

        self.plot_graph()

    def _quit(self, event):
        event.widget.quit()

    def _bind_keys(self):
        self.bind('<Escape>', self._quit)
        self.bind('q', self._quit)
        self.bind('f', self._toggle_fullscreen)

    def _toggle_fullscreen(self, event):
        g = self.geometry()
        self.geometry(self._geometry)
        self._geometry = g

    def plot_graph(self):
        now = UTCDateTime()
        if self.drum_plot:
            self.stop_time = UTCDateTime(
                now.year, now.month, now.day, now.hour, 0, 0) + 3600
            self.start_time = self.stop_time - self.args.backtrace_time
        else:
            self.start_time = now - self.backtrace
            self.stop_time = now

        with self.lock:
            # leave some data left of our start for possible processing
            self.stream.trim(
                starttime=self.start_time - 120, nearest_sample=False)
            stream = self.stream.copy()

        try:
            logging.info(str(stream.split()))
            if not stream:
                raise Exception("Empty stream for plotting")

            if self.drum_plot :
                stream.merge()
                stream.trim(starttime=self.start_time, endtime=self.stop_time,
                            pad=True, nearest_sample=False)
            else:
                stream.merge(-1)
                stream.trim(starttime=self.start_time, endtime=self.stop_time)
            if self.drum_plot:
                self.plot_drum(stream)
            else:
                self.plot_lines(stream)
        except Exception as e:
            logging.error(e)
            pass
        self.after(int(self.args.update_time * 1000), self.plot_graph)

    def plot_drum(self, stream):
        title = stream[0].id
        if self.scale:
            title += ' - scale: ' + str(self.scale) + ' -'
        else:
            title += ' - autoscale -'
        title += " without filtering"
        self.figure.clear()
        stream.detrend()
        stream.filter("bandpass", freqmin=1/100, freqmax=1/90)
        stream.plot(
            fig=self.figure, type='dayplot', interval=self.args.x_scale,
            number_of_ticks=self.args.time_tick_nb, tick_format=self.args.tick_format,
            size=(self.args.x_size, self.args.y_size),
            x_labels_size=8, y_labels_size=8,
            title=title, title_size=14,
            linewidth=0.5, right_vertical_labels=False,
            vertical_scaling_range=self.args.scale,
            subplots_adjust_left=0.04, subplots_adjust_right=0.99,
            subplots_adjust_top=0.95, subplots_adjust_bottom=0.05,
            one_tick_per_line=True,
            color=self.color,
            show_y_UTC_label=False,
            events=self.events)

    def plot_lines(self, stream):
        for id_ in self.ids:
            if not any([tr.id == id_ for tr in stream]):
                net, sta, loc, cha = id_.split(".")
                header = {'network': net, 'station': sta, 'location': loc,
                          'channel': cha, 'starttime': self.start_time}
                data = np.zeros(2)
                stream.append(Trace(data=data, header=header))
        stream.sort()
        self.figure.clear()
        fig = self.figure
        # avoid the differing trace.processing attributes prohibiting to plot
        # single traces of one id together.
        for tr in stream:
            tr.stats.processing = []
        stream.plot(fig=fig, method="fast", draw=False, equal_scale=False,
                    size=(self.args.x_size, self.args.y_size), title="",
                    color='Blue', tick_format=self.args.tick_format,
                    number_of_ticks=self.args.time_tick_nb)
        fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
        bbox = dict(boxstyle="round", fc="w", alpha=0.8)
        path_effects = [withStroke(linewidth=4, foreground="w")]
        pad = 10
        for ax in fig.axes[::2]:
            if MATPLOTLIB_VERSION[0] >= 2:
                ax.set_facecolor("0.8")
            else:
                ax.set_axis_bgcolor("0.8")
        for id_, ax in zip(self.ids, fig.axes):
            ax.set_title("")
    
            try:
                text = ax.texts[0]
            # we should always have a single text, which is the stream
            # label of the axis, but catch index errors just in case
            except IndexError:
                pass
            else:
                text.set_fontsize(self.args.title_size)
            xlabels = ax.get_xticklabels()
            ylabels = ax.get_yticklabels()
            plt.setp(ylabels, ha="left", path_effects=path_effects)
            ax.yaxis.set_tick_params(pad=-pad)
            # treatment for bottom axes:
            if ax is fig.axes[-1]:
                plt.setp(
                    xlabels, va="bottom", size=self.args.time_legend_size, bbox=bbox)

                ax.xaxis.set_tick_params(pad=-pad)
            # all other axes
            else:
                plt.setp(xlabels, visible=False)
            locator = MaxNLocator(nbins=4, prune="both")
            ax.yaxis.set_major_locator(locator)
            ax.yaxis.grid(False)
            ax.grid(True, axis="x")
            if len(ax.lines) == 1:
                ydata = ax.lines[0].get_ydata()
                # if station has no data we add a dummy trace and we end up in
                # a line with either 2 or 4 zeros (2 if dummy line is cut off
                # at left edge of time axis)
                if len(ydata) in [4, 2] and not ydata.any():
                    plt.setp(ylabels, visible=False)
                    if MATPLOTLIB_VERSION[0] >= 2:
                        ax.set_facecolor("#ff6666")
                    else:
                        ax.set_axis_bgcolor("#ff6666")
        fig.axes[0].set_xlim(right=date2num(self.stop_time.datetime))
        fig.axes[0].set_xlim(left=date2num(self.start_time.datetime))
        if len(fig.axes) > 5:
            bbox["alpha"] = 0.6
        fig.text(0.99, 0.97, self.stop_time.strftime("%Y-%m-%d %H:%M:%S UTC"),
                 ha="right", va="top", bbox=bbox, fontsize="medium")
        fig.canvas.draw()

    def rgb_to_hex(self, red_value, green_value, blue_value):
        """
            converter for the colors gradient
        """
        return '#%02X%02X%02X' % (red_value, green_value, blue_value)

    def rainbow_color_generator(self, max_color):
        """
            Rainbow color generator
        """
        color_list = []
        frequency = 0.3
        for compteur_lignes in range_func(max_color):

            red = sin(frequency * compteur_lignes * 2 + 0) * 127 + 128
            green = sin(frequency * compteur_lignes * 2 + 2) * 127 + 128
            blue = sin(frequency * compteur_lignes * 2 + 4) * 127 + 128

            color_list.append(
                self.rgb_to_hex(red_value=red, green_value=green, blue_value=blue))

        return tuple(color_list)


class SeedlinkUpdater(SLClient):

    def __init__(self, stream, myargs=None, lock=None):
        # loglevel NOTSET delegates messages to parent logger
        super(SeedlinkUpdater, self).__init__()
        self.stream = stream
        self.lock = lock
        self.args = myargs

   
    def packet_handler(self, count, slpack):
        """
        for compatibility with obspy 0.10.3 renaming
        """
        self.packetHandler(count, slpack)

    def packetHandler(self, count, slpack):
        """
        Processes each packet received from the SeedLinkConnection.
        :type count: int
        :param count:  Packet counter.
        :type slpack: :class:`~obspy.seedlink.SLPacket`
        :param slpack: packet to process.
        :return: Boolean true if connection to SeedLink server should be
            closed and session terminated, false otherwise.
        """

        # check if not a complete packet
        if slpack is None or (slpack == SLPacket.SLNOPACKET) or \
                (slpack == SLPacket.SLERROR):
            return False

        # get basic packet info
        type = slpack.get_type()

        # process INFO packets here
        if type == SLPacket.TYPE_SLINF:
            return False
        if type == SLPacket.TYPE_SLINFT:
            logging.info("Complete INFO:" + self.slconn.getInfoString())
            if self.infolevel is not None:
                return True
            else:
                return False

        # process packet data
        trace = slpack.get_trace()
        if trace is None:
            logging.info(
                self.__class__.__name__ + ": blockette contains no trace")
            return False

        # new samples add to the main stream which is then trimmed
        with self.lock:
            self.stream += trace
            self.stream.merge(-1)
            for tr in self.stream:
                tr.stats.processing = []
        return False

    def getTraceIDs(self):
        """
        Return a list of SEED style Trace IDs that the SLClient is trying to
        fetch data for.
        """
        ids = []
        streams = self.slconn.get_streams()
        for stream in streams:
            net = stream.net
            sta = stream.station
            selectors = stream.get_selectors()
            for selector in selectors:
                if len(selector) == 3:
                    loc = ""
                else:
                    loc = selector[:2]
                cha = selector[-3:]
                ids.append(".".join((net, sta, loc, cha)))
        ids.sort()
        return ids


class EventUpdater():
    """
    Fetch list of seismic events
    """
    def __init__(self, stream, events, myargs=None, lock=None):
        self.stream = stream
        self.events = events
        self.args = myargs
        self.lock = lock
        warn_msg = "The resource identifier already exists and points to " + \
                   "another object. It will now point to the object " + \
                   "referred to by the new resource identifier."
        warnings.filterwarnings("ignore", warn_msg)

    def run(self):
        """
        Endless execution to update events. Does not terminate, to be run in a
        (daemon) thread.
        """
        while True:
            # no stream, reschedule event update in 20 seconds
            if not self.stream:
                time.sleep(20)
                continue
            try:
                events = self.get_events()
            except URLError as error:
                msg = "%s: %s\n" % (error.__class__.__name__, error)
                sys.stderr.write(msg)
            except Exception as error:
                msg = "%s: %s\n" % (error.__class__.__name__, error)
                sys.stderr.write(msg)
            else:
                self.update_events(events)
            time.sleep(self.args.events_update_time * 60)

    def get_events(self):
        """
        Method to fetch updated list of events to use in plot.
        """
        with self.lock:
            start = min([tr.stats.starttime for tr in self.stream])
            end = max([tr.stats.endtime for tr in self.stream])
        neries_emsc = Client("EMSC")
        events = neries_emsc.get_events(starttime=start, endtime=end,
                                          minmagnitude=self.args.events)
        return events

    def update_events(self, events):
        """
        Method to insert new events into list of events shared with the GUI.
        """
        with self.lock:
            self.events.clear()
            self.events.extend(events)


def _parse_time_with_suffix_to_seconds(timestring):
    """
    Parse a string to seconds as float.

    If string can be directly converted to a float it is interpreted as
    seconds. Otherwise the following suffixes can be appended, case
    insensitive: "s" for seconds, "m" for minutes, "h" for hours, "d" for days.

    >>> _parse_time_with_suffix_to_seconds("12.6")
    12.6
    >>> _parse_time_with_suffix_to_seconds("12.6s")
    12.6
    >>> _parse_time_with_suffix_to_minutes("12.6m")
    756.0
    >>> _parse_time_with_suffix_to_seconds("12.6h")
    45360.0

    :type timestring: str
    :param timestring: "s" for seconds, "m" for minutes, "h" for hours, "d" for
        days.
    :rtype: float
    """
    try:
        return float(timestring)
    except:
        timestring, suffix = timestring[:-1], timestring[-1].lower()
        mult = {'s': 1.0, 'm': 60.0, 'h': 3600.0, 'd': 3600.0 * 24}[suffix]
        return float(timestring) * mult


def _parse_time_with_suffix_to_minutes(timestring):
    """
    Parse a string to minutes as float.

    If string can be directly converted to a float it is interpreted as
    minutes. Otherwise the following suffixes can be appended, case
    insensitive: "s" for seconds, "m" for minutes, "h" for hours, "d" for days.

    >>> _parse_time_with_suffix_to_minutes("12.6")
    12.6
    >>> _parse_time_with_suffix_to_minutes("12.6s")
    0.21
    >>> _parse_time_with_suffix_to_minutes("12.6m")
    12.6
    >>> _parse_time_with_suffix_to_minutes("12.6h")
    756.0

    :type timestring: str
    :param timestring: "s" for seconds, "m" for minutes, "h" for hours, "d" for
        days.
    :rtype: float
    """
    try:
        return float(timestring)
    except:
        seconds = _parse_time_with_suffix_to_seconds(timestring)
    return seconds / 60.0


def main():
    parser = ArgumentParser(prog='seedlink_plotter',
                            description='Plot a realtime seismogram of a station',
                            formatter_class=ArgumentDefaultsHelpFormatter)
    parser.add_argument(
        '-s', '--seedlink_streams', type=str, required=True,
        help='The seedlink stream selector string. It has the format '
             '"stream1[:selectors1],stream2[:selectors2],...", with "stream" '
             'in "NETWORK"_"STATION" format and "selector" a space separated '
             'list of "LOCATION""CHANNEL", e.g. '
             '"IU_KONO:BHE BHN,MN_AQU:HH?.D".')
    parser.add_argument(
        '--scale', type=int, help='the scale to apply on data ex:50000', required=False)

    # Real-time parameters
    parser.add_argument('--seedlink_server', type=str,
                        help='the seedlink server to connect to with port. "\
                        "ex: rtserver.ipgp.fr:18000 ', required=True)
    parser.add_argument(
        '--x_scale', type=_parse_time_with_suffix_to_minutes,
        help='the number of minute to plot per line'
             ' The following suffixes can be used as well: "s" for seconds, '
             '"m" for minutes, "h" for hours and "d" for days.',
        default='60m')
    parser.add_argument('-b', '--backtrace_time',
                        help='the number of seconds to plot (3600=1h,86400=24h). The '
                        'following suffixes can be used as well: "m" for minutes, '
                        '"h" for hours and "d" for days.', required=True,
                        type=_parse_time_with_suffix_to_seconds,default='24h')
    parser.add_argument('--x_position', type=int,
                        help='the x position of the graph', required=False, default=0)
    parser.add_argument('--y_position', type=int,
                        help='the y position of the graph', required=False, default=0)
    parser.add_argument(
        '--x_size', type=int, help='the x size of the graph', required=False, default=800)
    parser.add_argument(
        '--y_size', type=int, help='the y size of the graph', required=False, default=600)
    parser.add_argument(
        '--title_size', type=int, help='the title size of each station in multichannel', required=False, default=10)
    parser.add_argument(
        '--time_legend_size', type=int, help='the size of time legend in multichannel', required=False, default=10)
    parser.add_argument(
        '--tick_format', type=str, help='the tick format of time legend ', required=False, default=None)
    parser.add_argument(
        '--time_tick_nb', type=int, help='the number of time tick', required=False)
    parser.add_argument(
        '--without-decoration', required=False, action='store_true',
        help=('the graph window will have no decorations. that means the '
              'window is not controlled by the window manager and can only '
              'be closed by killing the respective process.'))
    parser.add_argument(
        '--line_plot', help='regular real time plot for single station', required=False, action='store_true')
    parser.add_argument(
        '--rainbow', help='', required=False, action='store_true')
    parser.add_argument(
        '--nb_rainbow_colors', help='the numbers of colors for rainbow mode', required=False, default=10)
    parser.add_argument(
        '--update_time',
        help='time in seconds between each graphic update.'
        ' The following suffixes can be used as well: "s" for seconds, '
        '"m" for minutes, "h" for hours and "d" for days.',
        required=False, default=10,
        type=_parse_time_with_suffix_to_seconds)
    parser.add_argument('--events', required=False, default=None, type=float,
                        help='plot events using obspy.neries, specify minimum magnitude')
    parser.add_argument(
        '--events_update_time', required=False, default=10,
        help='time in minutes between each event data update. '
             ' The following suffixes can be used as well: "s" for seconds, '
             '"m" for minutes, "h" for hours and "d" for days.',
        type=_parse_time_with_suffix_to_minutes)
    parser.add_argument('-f', '--fullscreen', default=False,
                        action="store_true",
                        help='set to full screen on startup')
    parser.add_argument('-v', '--verbose', default=False,
                        action="store_true", dest="verbose",
                        help='show verbose debugging output')
    parser.add_argument('--force', default=False, action="store_true",
                        help='skip warning message and confirmation prompt '
                             'when opening a window without decoration')
    # parse the arguments
    args = parser.parse_args()

    if args.verbose:
        loglevel = logging.DEBUG
    else:
        loglevel = logging.CRITICAL
    logging.basicConfig(level=loglevel)

    # before anything else: warn user about window without decoration
    if args.without_decoration and not args.force:
        warning_ = ("Warning: You are about to open a window without "
                    "decoration that is not controlled via your Window "
                    "Manager. You can exit with <Ctrl>-C (as long as you do "
                    "not switch to another window with e.g. <Alt>-<Tab>)."
                    "\n\nType 'y' to continue.. ")
        if input_func(warning_) != "y":
            print("Aborting.")
            sys.exit()

    now = UTCDateTime()
    stream = Stream()
    events = Catalog()
    lock = threading.Lock()

    # cl is the seedlink client
    seedlink_client = SeedlinkUpdater(stream, myargs=args, lock=lock)
    seedlink_client.slconn.set_sl_address(args.seedlink_server)
    seedlink_client.multiselect = args.seedlink_streams

    # tes if drum plot or line plot
    if any([x in args.seedlink_streams for x in ", ?*"]) or args.line_plot:
        drum_plot = False
        if args.time_tick_nb is None:
            args.time_tick_nb = 5
        if args.tick_format is None:
            args.tick_format = '%H:%M:%S'
        round_start = UTCDateTime(now.year, now.month, now.day, now.hour, 0, 0)
        round_start = round_start + 3600 - args.backtrace_time
        seedlink_client.begin_time = (round_start).format_seedlink()

    else:
        drum_plot = True
        if args.time_tick_nb is None:
            args.time_tick_nb = 13
        if args.tick_format is None:
            args.tick_format = '%d/%m/%y %Hh'
    seedlink_client.begin_time = (now - args.backtrace_time).format_seedlink()

    seedlink_client.initialize()
    ids = seedlink_client.getTraceIDs()
    # start cl in a thread
    thread = threading.Thread(target=seedlink_client.run)
    thread.setDaemon(True)
    thread.start()

    # start another thread for event updating if requested
    if args.events is not None:
        event_updater = EventUpdater(
            stream=stream, events=events, myargs=args, lock=lock)
        thread = threading.Thread(target=event_updater.run)
        thread.setDaemon(True)
        thread.start()

    # Wait few seconds to get data for the first plot
    time.sleep(2)

    master = SeedlinkPlotter(stream=stream, events=events, myargs=args,
                             lock=lock, drum_plot=drum_plot,
                             trace_ids=ids)
    master.mainloop()

if __name__ == '__main__':
    main()
