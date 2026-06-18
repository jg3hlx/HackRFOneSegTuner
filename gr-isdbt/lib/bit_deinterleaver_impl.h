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

#ifndef INCLUDED_ISDBT_BIT_DEINTERLEAVER_IMPL_H
#define INCLUDED_ISDBT_BIT_DEINTERLEAVER_IMPL_H

#include <gnuradio/isdbt/bit_deinterleaver.h>

namespace gr {
  namespace isdbt {

    class bit_deinterleaver_impl : public bit_deinterleaver
    {
     private:

         static const int d_data_carriers_mode1; 
         static const int d_total_segments; 
         static const int d_total_layers; 

         static const int d_delay_qpsk[]; 
         static const int d_delay_16qam[]; 
         static const int d_delay_64qam[]; 
         
         int d_mode; 
         int d_layer;
         int d_const_size;
         int d_num_bits;
		 int d_nsegments;
         const int* d_delay;
         int d_carriers_per_segment; 
         int d_noutput;
         int d_noutput_real;
         unsigned d_interpolation;
         bool d_reset_interpolation;

         //Here are the symbols. To create an output I have to check
         //several symbols back. Where and how many depends on the 
         //constellation size. 
         //TODO deques are worse than circular_buffers. We should eventually migrate
         //them all to this structure. 
         std::deque<unsigned char> d_shift; 

         void init_params(int segments, int constellation_size);
         void handle_tmcc(const pmt::pmt_t& msg);

      // Where all the action really happens
      int work(int noutput_items,
                        gr_vector_const_void_star &input_items,
                        gr_vector_void_star &output_items);

     public:
      bit_deinterleaver_impl(int mode, int layer, int segments, int constellation_size);
      ~bit_deinterleaver_impl();
      unsigned interpolation() const { return d_interpolation; }
      void set_interpolation(unsigned interpolation)
      {
          d_interpolation = interpolation;
          set_relative_rate((uint64_t)interpolation, 1);
          set_output_multiple(interpolation);
      }

      void forecast(int noutput_items, gr_vector_int& ninput_items_required);
      int general_work(int noutput_items,
                     gr_vector_int& ninput_items,
                     gr_vector_const_void_star& input_items,
                     gr_vector_void_star& output_items);
    };

  } // namespace isdbt
} // namespace gr

#endif /* INCLUDED_ISDBT_BIT_DEINTERLEAVER_IMPL_H */

