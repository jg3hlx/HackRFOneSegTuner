/* -*- c++ -*- */
/*  
 * Copyright 2015, 2016, 2017, 2018, 2019, 2020, 2021
 *   Federico "Larroca" La Rocca <flarroca@fing.edu.uy>
 *   Pablo Belzarena 
 *   Gabriel Gomez Sena 
 *   Pablo Flores Guridi 
 *   Victor Gonzalez Barbone
 *
 *   Instituto de Ingenieria Electrica, Facultad de Ingenieria,
 *   Universidad de la Republica, Uruguay.
 *  
 * This is free software; you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation; either version 3, or (at your option)
 * any later version.
 *  
 * This software is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *  
 * You should have received a copy of the GNU General Public License
 * along with this software; see the file COPYING.  If not, write to
 * the Free Software Foundation, Inc., 51 Franklin Street,
 * Boston, MA 02110-1301, USA.
 *
 */

#ifdef HAVE_CONFIG_H
#include "config.h"
#endif

#include <gnuradio/io_signature.h>
#include "time_deinterleaver_impl.h"
#include <stdio.h>

namespace gr {
    namespace isdbt {

        static const int interleaveTable[3][8]={
          {0,4,8,16,0,0,0,0},
          {0,2,4,8,0,0,0,0},
          {0,1,2,4,0,0,0,0}
        };

        // TODO shouldn't these be defined somewhere else??
        const int time_deinterleaver_impl::d_data_carriers_mode1 = 96; 
        const int time_deinterleaver_impl::d_total_segments = 13; 

        time_deinterleaver::sptr
            time_deinterleaver::make(int mode, int segments_A, int length_A, int segments_B, int length_B, int segments_C, int length_C)
            {
                return gnuradio::get_initial_sptr
                    (new time_deinterleaver_impl(mode, segments_A, length_A, segments_B, length_B, segments_C, length_C));
            }

        /*
         * The private constructor
         */
        time_deinterleaver_impl::time_deinterleaver_impl(int mode, int segments_A, int length_A, int segments_B, int length_B, int segments_C, int length_C)
            : gr::sync_block("time_deinterleaver",
                    gr::io_signature::make(1, 1, sizeof(gr_complex)*d_total_segments*d_data_carriers_mode1*((int)pow(2.0,mode-1))),
                    gr::io_signature::make(1, 1, sizeof(gr_complex)*d_total_segments*d_data_carriers_mode1*((int)pow(2.0,mode-1))))
        {
            d_mode = mode; 
            d_carriers_per_segment = d_data_carriers_mode1*((int)pow(2.0,mode-1)); 
            d_noutput = d_total_segments*d_carriers_per_segment; 

            init_params(segments_A,length_A,segments_B,length_B,segments_C,length_C);

            message_port_register_in(pmt::mp("params"));
            set_msg_handler(pmt::mp("params"),[this](const pmt::pmt_t& msg) {
              handle_tmcc(msg);
            });
        }

        /*
         * Our virtual destructor.
         */
        time_deinterleaver_impl::~time_deinterleaver_impl()
        {
            for (unsigned int i=0; i<d_shift.size();i++){
                delete d_shift.back();
                d_shift.pop_back();
            }
        }

        void time_deinterleaver_impl::init_params(int segments_A, int length_A, int segments_B, int length_B, int segments_C, int length_C) {
            d_I_A = length_A; 
            d_I_B = length_B; 
            d_I_C = length_C; 

            // I check if the total segments are what they should
            assert((segments_A + segments_B + segments_C) == d_total_segments);

            d_nsegments_A = segments_A; 
            d_nsegments_B = segments_B; 
            d_nsegments_C = segments_C; 

            int mi = 0;
            d_shift.clear();

            for (int segment=0; segment<d_nsegments_A; segment++)
            {
                for (int carrier = 0; carrier<d_carriers_per_segment; carrier++)
               {
                    mi = (5*carrier) % d_data_carriers_mode1; 
                    //d_shift.push_back(new std::deque<gr_complex>(d_I*(d_data_carriers_mode1-1-mi),0)); 
                    d_shift.push_back(new boost::circular_buffer<gr_complex>(d_I_A*(d_data_carriers_mode1-1-mi)+1,0)); 
                }
            }
            for (int segment=0; segment<d_nsegments_B; segment++)
            {
                for (int carrier = 0; carrier<d_carriers_per_segment; carrier++)
               {
                    mi = (5*carrier) % d_data_carriers_mode1; 
                    //d_shift.push_back(new std::deque<gr_complex>(d_I*(d_data_carriers_mode1-1-mi),0)); 
                    d_shift.push_back(new boost::circular_buffer<gr_complex>(d_I_B*(d_data_carriers_mode1-1-mi)+1,0)); 
                }
            }
            for (int segment=0; segment<d_nsegments_C; segment++)
            {
                for (int carrier = 0; carrier<d_carriers_per_segment; carrier++)
               {
                    mi = (5*carrier) % d_data_carriers_mode1; 
                    //d_shift.push_back(new std::deque<gr_complex>(d_I*(d_data_carriers_mode1-1-mi),0)); 
                    d_shift.push_back(new boost::circular_buffer<gr_complex>(d_I_C*(d_data_carriers_mode1-1-mi)+1,0)); 
                }
            }

        }

        void time_deinterleaver_impl::handle_tmcc(const pmt::pmt_t& msg) {
          if (is_u8vector(msg)) {
            std::vector<uint8_t> tmcc=u8vector_elements(msg);
            if (tmcc.size()==204) {
              int length_A=((tmcc[34]<<2)|(tmcc[35]<<1)|tmcc[36]);
              int length_B=((tmcc[47]<<2)|(tmcc[48]<<1)|tmcc[49]);
              int length_C=((tmcc[60]<<2)|(tmcc[61]<<1)|tmcc[62]);
              int segments_A=((tmcc[37]<<3)|(tmcc[38]<<2)|(tmcc[39]<<1)|tmcc[40]);
              int segments_B=((tmcc[50]<<3)|(tmcc[51]<<2)|(tmcc[52]<<1)|tmcc[53]);
              int segments_C=((tmcc[63]<<3)|(tmcc[64]<<2)|(tmcc[65]<<1)|tmcc[66]);

              if (segments_A>13) segments_A=0;
              if (segments_B>13) segments_B=0;
              if (segments_C>13) segments_C=0;

              length_A=interleaveTable[d_mode-1][length_A&7];
              length_B=interleaveTable[d_mode-1][length_B&7];
              length_C=interleaveTable[d_mode-1][length_C&7];

              if (segments_A!=d_nsegments_A || segments_B!=d_nsegments_B || segments_C!=d_nsegments_C ||
                  length_A!=d_I_A || length_B!=d_I_B || length_C!=d_I_C) {
                printf("time deinterleaver: reinitializing params... (%d[%d], %d[%d], %d[%d])\n",
                  segments_A, length_A,
                  segments_B, length_B,
                  segments_C, length_C
                );
                init_params(segments_A,length_A,segments_B,length_B,segments_C,length_C);
              }
            }
          }
        }

        int
            time_deinterleaver_impl::work(int noutput_items,
                    gr_vector_const_void_star &input_items,
                    gr_vector_void_star &output_items)
            {
                const gr_complex *in = (const gr_complex *) input_items[0];
                gr_complex *out = (gr_complex *) output_items[0];

                // TODO CHECK the tag propagation policy for the frame 
                // beginnning. 

                for (int i=0; i<noutput_items; i++)
                {
                    for (int carrier=0; carrier<d_noutput; carrier++)
                    {
                        // a simple FIFO queue performs the interleaving. 
                        // The "difficult" part is setting the correct sizes 
                        // for each queue. 
                        d_shift[carrier]->push_back(in[i*d_noutput + carrier]);
                        out[i*d_noutput + carrier] = d_shift[carrier]->front();
                        //d_shift[carrier]->pop_front(); 
                    }
                }
                // Tell runtime system how many output items we produced.
                return noutput_items;
            }

    } /* namespace isdbt */
} /* namespace gr */

