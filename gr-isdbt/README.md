# modified

this is a modified version of [gr-isdbt](https://github.com/git-artes/gr-isdbt), with a focus on improving the receiver part.

# ISDB-T transceiver in GNU Radio

**An open source implementation of a transceiver (i.e. receiver and transmitter) for the Digital Television standard ISDB-T (ARIB's STD-B31) in GNU Radio.**

**If you find the code useful, please consider starring the repository and/or citing our research paper (e.g. https://iie.fing.edu.uy/publicaciones/2020/LFAIM20/ regarding the transmitter or https://iie.fing.edu.uy/publicaciones/2016/LFGGB16/ regarding the receiver).**

**IMPORTANT**: this requires GNU Radio 3.10. it could work with previous versions but that has not been tested.

## preface

Japan, the Philippines and most South American countries have adopted the ISDB-T digital television standard.
it is known for providing good performance in mobile situations.

interest in the standard by hobbyists has been rather lacking, perhaps due to its usage within (mostly) developing countries. DVB-T and ATSC have mature support within GNU Radio, whereas ISDB-T doesn't (at least upstream).
even hardware manufacturers aren't interested, with most ISDB-T dongles only featuring 1-seg demodulation (the low-quality mobile portion) and deplorable software/kernel support (even on Windows!) when compared to their DVB-T/ATSC counterparts.

hereby I give my utmost appreciation to git-artes for dedicating countless hours in the development of a full-featured ISDB-T transceiver.
however, I've found a couple issues and drawbacks while using it, including synchronization problems, the need to acquire and manually set all parameters and poor multipath performance, so I've decided to address those issues and make the receiver part easier to set up.
my goal is to eventually create a mostly setup-free analyzer/viewer...

Here in South America we use the so-called "international" version, or ISDB-Tb/SBTVD (ABNT NBR 15601). However, the transmission scheme is exactly the same as in the original version, thus both references are equivalent.

Since ISDB-T is similar to DVB-T, some of our blocks are heavily based on Bogdan Diaconescu's (BogdanDIA on github) DVB-T implementation (see https://github.com/BogdanDIA/gr-dvbt, which is now part of GNU Radio's base code). The transmitter side is based on the work of Javier and Santiago at https://github.com/jhernandezbaraibar/gr-isdbt-Tx.

Any help and/or feedback is welcome.
in particular, reception reports including constellation and estimated channel gains!

## how to use

### requirements

- a fast enough processor to perform modulation/demodulation. my Core i5 (Ivy Bridge) CPU is barely able to, so you might consider that as a minimum.
  - you may disregard this if not willing to demodulate/modulate in real-time (e.g. processing an I/Q file). probably not what you want though.
- an SDR (software-defined radio) receiver supporting at least ~8.12MHz of bandwidth, such as SDRplay, Airspy R2, HackRF or USRP.
  - sadly, RTL-SDR only does up to 2.56MHz, so it's not sufficient. sorry!
    - you might have some luck decoding in 1-seg mode by using a resampler block, but why not use the RTL's ISDB-T support at this point?
  - if using the transmitter, you need an SDR transmitter (HackRF and USRP are two examples). I haven't tested the transmitter at all.
- time and patience to move your antenna around for optimal reception. the demodulator lacks most of the fancy bits a consumer TV has (notably reception robustness). while it should perform just as good as this TV from 2018, it's not perfect and any actual TV will outperform this software receiver thanks to the use of dedicated DSP chips and advanced algorithms.

### receiver

the **receiver** is now complete and (somewhat) battle-tested.
it is capable of demodulating the complete and 1-seg ISDB-T spectrum. we foresee four modes of operation:

- **Obtaining the transmission parameters.**
  - ISDB-T has several transmission parameters which may be selected by the transmitter and may (and probably will) change among channels and segments. while I've added some support for automatic parameter setup, certain blocks (in particular, the bit deinterleaver) still cannot do so, and I haven't figured out why yet.
  - a simple example is provided (see `examples/obtaining_parameters.grc`). this originally was used to obtain the transmission parameters, but now has been repurposed to acquiring the correct transmission mode and guard interval for the rest of examples. the name of that example is kind of a misnomer now.
  - load `obtaining_parameters.grc` in GNU Radio Companion. run it, and play around with the values until you see a fixed peak.
- **Vector Analyzer.**
  - load `examples/viewing_the_constellation.grc` to view the received complex symbols.
  - use the parameters you determined using the previous example.
  - this is the first example that makes use of the ISDB-T blocks.
  - this example will allow you to see the constellation, incoming spectrum and estimated channel gains.
  - it has been tested with many guard interval lengths and modes, albeit signals in mode 3 work best.
  - an "excellent" signal consists of a sharp constellation (dots converged to form a grid) and mostly flat channel gain.
- **Complete decoding and displaying the video/audio.**
  - now this is what you're probably looking for. setup is a bit harder, but don't hesitate!
  - load `examples/rx_demo.grc` in GNU Radio Companion. it contains a typical full decoder setup for Layer B (ISDB-T has three "layers" with the first one usually reserved for 1-seg (mobile signal and identification) and the other two for the rest) with an SDRplay receiver.
  - tweak the example. set the frequency, RF gains, OFDM guard interval and transmission mode. change the source if needed.
  - there are three sinks in the final output stage.
    - one of them is a null sink, which discards the output. it should be useful if you want to check the BER but not actually log anything.
    - the other one is a file sink to `result_layer_b.ts`. this actually should be a pipe. enable the two Python blocks so it creates the pipe for you and starts `ffplay`. this will allow you to watch the decoded signal.
    - the last sink points to a file. use this if you want to record incoming video/audio.
  - run the example.
    - the GUI displays constellation and pre/post-Viterbi BER.
    - the pre-Viterbi BER must be sufficiently low for error-free decoding. the threshold varies depending on the constellation size and code rate, but some estimates for a 64QAM constellation are:
      - `1/2`: <-1.35
      - `2/3`: <-1.66
      - `3/4`: <-1.93
    - adjust your antenna until the dots in the constellation converge and the BER decreases substantially.
    - the post-Viterbi BER will be most likely dead-locked high if the bit deinterleaver is not set up correctly or the pre-Viterbi BER exceeds the threshold. if it peaks, it means there are uncorrectable bit errors.
      - if you believe the bit deinterleaver isn't set up, observe the console output and look for the Bit Deinterleaver parameter change. stop and set up the block with the right parameter (segment count), then run it again.
      - you may want to configure the rest of parameters, but don't worry. it's only the bit deinterleaver that requires manual setup.
    - in case something goes wrong, hit the Reset button.
  - the output is a Transport Stream file which may be played by a compatible media player such as ffplay or mpv. if you're using the pipe, ffplay will be started and a couple seconds after data goes through you should be able to watch the live broadcast/transmission.
- **Complete, complete (for real this time) decoding of all three layers.**
  - if your CPU is fast enough, the `examples/rx_demo_multi.grc` example contains a full decoder for all three layers.
  - load it, set the parameters up, adjust the bit deinterleavers and you should have three files containing separate layers.
- **Signal analyzer.**
  - the original objective with the project is to develop a relatively inexpensive ISDB-T measurement equipment. there was an example for this, but it's no longer there.

### transmitter

I haven't tested the transmitter much as my focus is on the receiver, but it should be working as it is complete and tested by the original development team.

- It works perfectly fine on software together with the receiver (see examples/full_transceiver.grc). A transport stream file to be used in this example is available on the project's webpage, but you can also use your own as long as it fits within the constraints of a constant bit rate stream. If you are not interested in "seeing" a video image, simply feed it with random bytes.
- Over the air transmission. We are currently able to transmit and receive the signal with SDRs (a B200 worked best for us as a transmitter) and we are successfully testing it on commercial TVs (see examples/tx_demo.grc which uses the TS files we share in our webpage).
- If you want to transmit your own videos (or your webcam) you may follow our step-by-step guide in https://iie.fing.edu.uy/investigacion/grupos/artes/wp-content/uploads/sites/13/2019/12/transmitting_webcam_or_videos.pdf.

For more information (papers, recordings of ISDB-T signals, etc.) please visit our webpage: http://iie.fing.edu.uy/investigacion/grupos/artes/gr-isdbt/.

## build instructions

For a system wide installation:

```
git clone https://github.com/tildearrow/gr-isdbt.git
cd gr-isdbt
mkdir build
cd build
cmake -DCMAKE_C_FLAGS=-O2 -DCMAKE_CXX_FLAGS=-O2 -DCMAKE_BUILD_TYPE=Release ..
make && sudo make install
```

For a user space installation, or GNU Radio installed in a location different from the default location /usr/local: (not well-tested!)

```
git clone https://github.com/tildearrow/gr-isdbt.git
cd gr-isdbt
mkdir build
cd build
cmake -DCMAKE_INSTALL_PREFIX=<your_GNURadio_install_dir> -DCMAKE_C_FLAGS=-O2 -DCMAKE_CXX_FLAGS=-O2 -DCMAKE_BUILD_TYPE=Release ..
make && make install
```

Please note that if you used PyBOMBS to install GNU Radio the `CMAKE_INSTALL_PREFIX` should point to the PyBOMBS prefix.

On Debian/Ubuntu based distributions, you may have to run `sudo ldconfig` afterwards.

### remarks

- Instructions above assume you have downloaded and compiled GNU Radio (either with the build-gnuradio script or with PyBOMBS). If you've used a pre-compiled binary package (like in $ sudo apt-get install gnuradio), then you should also install gnuradio-dev (and naturally cmake and git, if they were not installed, plus libboost-all-dev, libcppunit-dev, liblog4cpp5-dev, swig, liborc-dev and libgsl-dev). A one-liner for all these is `$sudo apt-get install gnuradio-dev cmake git libboost-all-dev libcppunit-dev liblog4cpp5-dev swig liborc-dev libgsl-dev clang-format`.
- The above build instructions are general. You may accelerate the compilation time by using the -j flag. Please visit http://www.math-linux.com/linux/tip-of-the-day/article/speedup-gnu-make-build-and-compilation-process for a guide.
- Note that gr-isdbt makes heavy use of VOLK. A profile should be run to make the best out of it. Please visit https://gnuradio.org/redmine/projects/gnuradio/wiki/Volk for instructions, or simply run`volk_profile`.

## FAQ

*Q*: Cmake complains about unmet requirements. What's the problem?
*A*: You should read the errors carefully (though we reckon they are sometimes mysterious). Most probably is a missing library. Candidates are Boost (in Ubuntu libboost-all-dev) or libcppunit (in Ubuntu libcppunit-dev).

*Q*: Cmake complains about some Policy CMP0026 and LOCATION target property and who knows what else. Again, what's the problem?
*A*: This is a problem with using Cmake with a version >= 3, which is installed in Ubuntu 16, for instance. The good news is that you may ignore all these warnings.

*Q*: It is not compiling. What's the problem?
*A*: Again, you should read carefully the errors. Again, it's most probably a missing library, for instance log4cpp (in Ubuntu liblog4cpp5-dev). If the problem is with the API of GNU Radio, you should update it.

*Q*: I got the following error: "ModuleNotFoundError: No module named 'isdbt'". What's wrong?

*A*: You probably didn't setup the PYTHONPATH correctly. It should include at least /usr/local/lib/python3/dist-packages. For a system-wide solution, you may edit `/etc/environment` and include the following line `PYTHONPATH="$PYTHONPATH:/usr/local/lib/python3/dist-packages"`.

*Q*: I got the following error: "AttributeError: 'module' object has no attribute 'viterbi_decoder'" (or some other block). Why?
*A*: This problem may be generated by several factors. Did you "sudo ldconfig"? Do you have PYTHONPATH set? (It should include at least /usr/local/lib/python3/dist-packages). Another possibility is that you don't have swig installed (in this case, you must uninstall gr-isdbt, delete CMakeCache.txt in the build directory, and re-install; that is, after installing swig).

*Q*: Video is not playing. Why?
*A*: In our experience, the best player is ffplay, which comes along ffmpeg. You should try it.

*Q*: It complains about `AttributeError: 'gnuradio.gr.gr_python.logger' object has no attribute 'warning'`. Why?
*A*: This is a bug in certain versions of GNU Radio. See https://github.com/gnuradio/gnuradio/issues/6923 for a solution (or simply turn real-time scheduler to `off`).

## footnotes

IIE Instituto de Ingeniería Eléctrica
Facultad de Ingeniería
Universidad de la República
Montevideo, Uruguay
http://iie.fing.edu.uy/investigacion/grupos/artes/

Please refer to the LICENSE file for contact information and further credits.
