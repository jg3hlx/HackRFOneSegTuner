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
#include "bit_deinterleaver_impl.h"

#include <stdio.h>

namespace gr {
    namespace isdbt {

        // shouldn't these go somewhere else??
        const int bit_deinterleaver_impl::
            d_data_carriers_mode1 = 96; 
        const int bit_deinterleaver_impl::
            d_total_segments = 13; 
        const int bit_deinterleaver_impl::
            d_total_layers = 1; 

        const int bit_deinterleaver_impl::
            d_delay_qpsk[2] = {0, 120}; 
        const int bit_deinterleaver_impl::
            d_delay_16qam[4] = {0, 40, 80, 120}; 
        const int bit_deinterleaver_impl::
            d_delay_64qam[6] = {0, 24, 48, 72, 96, 120}; 

        // assume QPSK for unused
        static const float consSizeTable[8]={
          4, 4, 16, 64, 4, 4, 4, 4
        };

        bit_deinterleaver::sptr
            bit_deinterleaver::make(int mode, int layer, int segments, int constellation_size)
            {
                return gnuradio::get_initial_sptr
                    (new bit_deinterleaver_impl(mode, layer, segments, constellation_size));
            }

        /*
         * The private constructor
         */
        bit_deinterleaver_impl::
            bit_deinterleaver_impl(int mode, int layer, int segments, int constellation_size)
            	: gr::block("bit_deinterleaver",
                    gr::io_signature::make(1, 1, 
                        sizeof(unsigned char) * d_total_segments *
                        d_data_carriers_mode1 * ((int)pow(2.0, mode-1))),
                   // gr::io_signature::make3(1, 1, sizeof(unsigned char)), d_total_segments * d_data_carriers_mode1 * ((int)pow(2.0, mode-1))) Original implementation
                       gr::io_signature::make(1, 1, sizeof(unsigned char))) //Implementation that still works
                                       //gr::io_signature::make3(1, 3, sizeof(unsigned char), sizeof(unsigned char), sizeof(unsigned char)), d_total_segments* d_data_carriers_mode1 * ((int)pow(2.0, mode-1)))
                                       //gr::io_signature::make3(1, 3, sizeof(unsigned char), sizeof(unsigned char), sizeof(unsigned char)), (segments_A* d_data_carriers_mode1 * ((int)pow(2.0, mode-1)), segments_B* d_data_carriers_mode1 * ((int)pow(2.0, mode-1)), segments_C* d_data_carriers_mode1 * ((int)pow(2.0, mode-1))))
        {
            d_mode = mode; 
            d_layer = layer;
            d_carriers_per_segment = d_data_carriers_mode1 * 
                ((int)pow(2.0, mode-1)); 
            d_noutput = d_total_segments * d_carriers_per_segment; 
	    printf("d_noutput: %d\n",d_noutput);

            init_params(segments,constellation_size);
             set_interpolation(d_nsegments * d_data_carriers_mode1 * ((int)pow(2.0, d_mode-1)));

            d_reset_interpolation=false;

            message_port_register_in(pmt::mp("params"));
            set_msg_handler(pmt::mp("params"),[this](const pmt::pmt_t& msg) {
              handle_tmcc(msg);
            });

            // Init TMCC params change message port
            message_port_register_out(pmt::mp("changed"));
        }

        /*
         * Our virtual destructor.
         */
        bit_deinterleaver_impl::~bit_deinterleaver_impl()
        {
        }

        void bit_deinterleaver_impl::init_params(int segments, int constellation_size) {
            d_const_size = constellation_size;
            d_num_bits = log2(constellation_size);
	    d_nsegments = segments;
            printf("Segments: %d\n", segments);

            d_noutput_real = d_nsegments * d_carriers_per_segment; 
			printf("d_noutput REAL: %d\n",d_noutput_real);

            if (d_const_size==4) {
				d_delay = d_delay_qpsk;
			} else if (d_const_size==16) {
				d_delay = d_delay_16qam;
			} else if (d_const_size==64) {
				d_delay = d_delay_64qam;
			} else {
				printf("bit_deinterleaver: error in d_const_size %d\n",d_const_size);                  
			}

            //set_min_noutput_items(d_noutput_real);
            d_shift=std::deque<unsigned char>(120,0);
        }

        void bit_deinterleaver_impl::handle_tmcc(const pmt::pmt_t& msg) {
          if (is_u8vector(msg)) {
            std::vector<uint8_t> tmcc=u8vector_elements(msg);
            if (tmcc.size()==204) {
              int segments[3];
              int constellation_size[3];
              segments[0]=((tmcc[37]<<3)|(tmcc[38]<<2)|(tmcc[39]<<1)|tmcc[40]);
              segments[1]=((tmcc[50]<<3)|(tmcc[51]<<2)|(tmcc[52]<<1)|tmcc[53]);
              segments[2]=((tmcc[63]<<3)|(tmcc[64]<<2)|(tmcc[65]<<1)|tmcc[66]);
              constellation_size[0]=((tmcc[28]<<2) | (tmcc[29]<<1)| (tmcc[30]));
              constellation_size[1]=((tmcc[41]<<2) | (tmcc[42]<<1)| (tmcc[43]));
              constellation_size[2]=((tmcc[54]<<2) | (tmcc[55]<<1)| (tmcc[56]));
        
              for (int i=0; i<3; i++) {
                if (segments[i]>13) segments[i]=0;
                constellation_size[i]=consSizeTable[constellation_size[i]&7];
              }

              if (segments[d_layer]!=d_nsegments || constellation_size[d_layer]!=d_const_size) {
                printf("bit deinterleaver: reinitializing params... (%d/%d)\n",segments[d_layer],constellation_size[d_layer]);
                init_params(segments[d_layer],constellation_size[d_layer]);
                d_reset_interpolation=true;
              }
            }
          }
        }

        /*
         * Our work function.
         */
        int bit_deinterleaver_impl::work(int noutput_items,
                        gr_vector_const_void_star &input_items,
                        gr_vector_void_star &output_items)
            {	
                const unsigned char *in = (const unsigned char*) input_items[0];
                unsigned char *out = (unsigned char *) output_items[0];
                //unsigned char *out_A = (unsigned char *) output_items[0];
				//unsigned char *out_B = (unsigned char *) output_items[1];
				//unsigned char *out_C = (unsigned char *) output_items[2];
               
				//bool out_B_connected = output_items.size()>=2;
				//bool out_C_connected = output_items.size()>=3;

				// Do <+signal processing+>
                unsigned char aux; 
                unsigned char mask; 
                        //printf("noutput_items %d\n",noutput_items);
			//printf("---BIT DEINTERLEAVER-> noutput_items = %d\n", noutput_items);				
			for (int i=0; i<noutput_items/d_noutput_real; i++)
			{
                        for (int carrier = 0; carrier<d_noutput_real; carrier++)
                        {
                            	// add new input symbol at beginning of container
                            	// Older symbols are at bigger indexes for consistency
                            	// with the d_delay implementation. 
                            	d_shift.push_front(in[i*d_noutput + carrier]); 
                            	// Initialize aux variables to construct output
                            	aux = 0; 
                            	mask = 1; 
                            	for (int b=0; b<d_num_bits; b++){
                                // Least significant bits more delayed in interleaver,
                                // so now delay more the most significant bits
                                aux |= d_shift[d_delay[b]] & mask; 
                                mask = mask << 1;  
                            	
								}
								
								d_shift.pop_back();
								out[i*d_noutput_real+carrier] = aux; 
								
						}
                          
					//} 
                }
                // Tell runtime system how many output items we produced.
                return noutput_items;
            }

void bit_deinterleaver_impl::forecast(int noutput_items, gr_vector_int& ninput_items_required)
{
    unsigned ninputs = ninput_items_required.size();
    for (unsigned i = 0; i < ninputs; i++) {
        ninput_items_required[i] = noutput_items / interpolation() + history() - 1;
    }
}

int bit_deinterleaver_impl::general_work(int noutput_items,
                                    gr_vector_int& ninput_items,
                                    gr_vector_const_void_star& input_items,
                                    gr_vector_void_star& output_items)
{
    if (d_reset_interpolation) {
      printf("RESET INTERPOLATION\n");
      set_interpolation(d_nsegments * d_data_carriers_mode1 * ((int)pow(2.0, d_mode-1)));
      d_reset_interpolation=false;
      //d_shift=std::deque<unsigned char>(120,0);
      consume_each(ninput_items[0]);
      message_port_pub(pmt::mp("changed"),pmt::PMT_NIL);
      return 0;
    }
    int r = work(noutput_items, input_items, output_items);
    if (r > 0)
        consume_each(r / interpolation());
    return r;
}


    } /* namespace isdbt */
} /* namespace gr */

