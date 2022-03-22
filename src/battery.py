# Copyright (c) Meta Platforms, Inc. and affiliates.
# This source code is licensed under the CC-BY-NC license found in the
# LICENSE file in the root directory of this source tree.

import numpy as np

class Battery:
    capacity = 0 # Max MWh storage capacity
    current_load = 0 # Current load in the battery, in MWh

    def __init__(self, capacity, current_load=0):
        self.capacity = capacity
        self.current_load = current_load

    # charge the battery based on an hourly load
    # returns the total load after charging with input_load
    def charge(self, input_load):
        self.current_load = self.current_load + input_load
        if(self.current_load > self.capacity):
            self.current_load = self.capacity
        return self.current_load

    # returns how much energy is discharged when
    # output_load is drawn from the battery in an hour
    def discharge(self, output_load):
        self.current_load = self.current_load - output_load
        if(self.current_load < 0): # not enough battery load
            lacking_amount = self.current_load
            self.current_load = 0
            return output_load + lacking_amount
        return output_load

    def is_full(self):
        return (self.capacity == self.current_load)
    
    # calculate the minimum battery capacity required
    # to be able to charge it with input_load
    # amount of energy within an hour and
    # expand the existing capacity with that amount
    def find_and_init_capacity(self, input_load):
        self.capacity = self.capacity + input_load

# Battery model that includes efficiency and 
# linear charging/discharging rate limits with respect to battery capacity
# refer to C/L/C model in following reference for details: 
# "Tractable lithium-ion storage models for optimizing energy systems." 
# Energy Informatics 2.1 (2019): 1-22.
class Battery2:
    capacity = 0 # Max MWh storage capacity
    current_load = 0 # Current load in the battery, in MWh
    
    # charging and discharging efficiency, including DC-AC inverter loss
    eff_c = 1
    eff_d = 1

    # Maximum charging energy in one time step 
    # is limited by (u * applied power) + v
    upper_lim_u = 0
    upper_lim_v = 1

    # Maximum discharged energy in one time step 
    # is limited by (u * applied power) + v
    lower_lim_u = 0
    lower_lim_v = 0


    # defaults for lithium NMC cell
    def __init__(self, capacity, current_load=0,
                 eff_c = 0.98, eff_d = 1.05,
                 upper_u = -0.125, upper_v = 1,
                 lower_u = 0.05, lower_v = 0):
        self.capacity = capacity
        self.current_load = current_load

        self.eff_c = eff_c
        self.eff_d = eff_d
        self.upper_lim_u = upper_u
        self.upper_lim_v = upper_v
        self.lower_lim_u = lower_u
        self.lower_lim_v = lower_v

    def calc_max_charge(self):

        # energy content in current (next) time step: b_k (b_{k+1}, which is just b_k + p_k*eff_c)
        # charging power in current time step: p_k
        # b_{k+1} <= u * p_k + v is equivalent to
        # p_k <= (v - b_k) / (eff_c - u)
        max_charge = min(self.capacity/self.eff_c, 
                         (self.upper_lim_v*self.capacity - self.current_load)/(self.eff_c - self.upper_lim_u))
        return max_charge

    def calc_max_discharge(self):

        # energy content in current (next) time step: b_k (b_{k+1}, which is just b_k - p_k*eff_d)
        # charging power in current time step: p_k
        # b_{k+1} <= u * p_k + v is equivalent to
        # p_k <= (b_k - v) / (u + eff_d)
        max_discharge = min(self.capacity/self.eff_d, 
                            (self.current_load - self.lower_lim_v*self.capacity)/(self.lower_lim_u + self.eff_d))
        return max_discharge


    # charge the battery based on an hourly load
    # returns the total load after charging with input_load
    def charge(self, input_load):
        max_charge = self.calc_max_charge()
        self.current_load = self.current_load + min(max_charge, input_load) * self.eff_c
        return self.current_load

    # returns how much energy is discharged when
    # output_load is drawn from the battery in an hour
    def discharge(self, output_load):
        max_discharge = self.calc_max_discharge()
        self.current_load = self.current_load - min(max_discharge, output_load) * self.eff_d
        if(max_discharge < output_load): # not enough battery load
            return max_discharge
        return output_load

    def is_full(self):
        return (self.capacity == self.current_load)
    
    # calculate the minimum battery capacity required
    # to be able to charge it with input_load
    # amount of energy within an hour and
    # expand the existing capacity with that amount
    def find_and_init_capacity(self, input_load):

        self.capacity = self.capacity + input_load*self.eff_d

        # increase the capacity until we can discharge input_load
        # TODO: find analytical value for this
        new_capacity = input_load*self.eff_d
        while True:
            power_lim = (new_capacity - self.lower_lim_v*self.capacity)/(self.lower_lim_u + self.eff_d)
            if power_lim < input_load:
                self.capacity += 0.1
                new_capacity += 0.1
            else:
                break
    
# return True if battery can meet all demand, False otherwise
def sim_battery_247(df_ren, df_dc_pow, b):

    for i in range(df_dc_pow.shape[0]):
        ren_mw = df_ren[i]
        df_dc = df_dc_pow["avg_dc_power_mw"][i]
        net_load = ren_mw - df_dc

        # surplus, charge
        if net_load > 0:
            b.charge(net_load)

        else:
            # deficit, discharge
            actual_discharge = b.discharge(-net_load)
            # if we couldnt discharge enough, exit
            if actual_discharge < -net_load:
                return False
    return True



# binary search for smallest battery size that meets all demand    
def calculate_247_battery_capacity_b2_sim(df_ren, df_dc_pow, max_bsize):

    # first check special case, no battery:
    if sim_battery_247(df_ren, df_dc_pow, Battery2(0,0)):
        return 0

    l = 0
    u = max_bsize
    while u - l > 0.1:
        med = (u + l) / 2
        if sim_battery_247(df_ren, df_dc_pow, Battery2(med,med)):
            u = med
        else:
            l = med

    # check if max size was too small
    if u == max_bsize:
        return np.nan
    return med

# binary search for smallest battery size that meets all demand    
def calculate_247_battery_capacity_b1_sim(df_ren, df_dc_pow, max_bsize):

    # first check special case, no battery:
    if sim_battery_247(df_ren, df_dc_pow, Battery(0,0)):
        return 0

    l = 0
    u = max_bsize
    while u - l > 0.1:
        med = (u + l) / 2
        if sim_battery_247(df_ren, df_dc_pow, Battery(med,med)):
            u = med
        else:
            l = med

    # check if max size was too small
    if u == max_bsize:
        return np.nan
    return med
        
# Takes renewable supply and dc power as input dataframes
# returns how much battery capacity is needed to make
# dc operate on renewables 24/7
def calculate_247_battery_capacity(df_ren, df_dc_pow):
    battery_cap = 0 # return value stored here, capacity needed
    daily_net_load = 0 # for calculating infeasible cases
    b = Battery(0) # start with an empty battery

    for i in range(df_dc_pow.shape[0]):
        ren_mw = df_ren[i]
        df_dc = df_dc_pow["avg_dc_power_mw"][i]
        daily_net_load += ren_mw - df_dc

        if df_dc > ren_mw:  # if there's not enough renewable supply, need to discharge
            if(b.capacity == 0):
                b.find_and_init_capacity(df_dc - ren_mw) # find how much battery cap needs to be
            else:
                load_before = b.current_load
                if(load_before == 0):
                    b.find_and_init_capacity(df_dc - ren_mw)
                else:
                    b.discharge(df_dc - ren_mw)
                    load_after = b.current_load
                    if(load_after == 0):
                        b.find_and_init_capacity((df_dc - ren_mw) - load_before)
        else:  # there's excess renewable supply, charge batteries
            if b.capacity > 0:
                b.charge(ren_mw-df_dc)
            elif b.is_full():
                b = Battery(0)

        if b.capacity > 0 and battery_cap != np.nan:
            battery_cap = max(battery_cap, b.capacity)
            #print(i)
            #print(battery_cap)
 
        # daily check, battery impossible case
        # if the battery cannot be filled fully in 3 days, assume it's infeasible
        # return np.nan
        if (i + 1) % 72 == 0:
            if daily_net_load < 0:
                battery_cap = np.nan
                break
            else:
                daily_net_load = 0

    return battery_cap

# Takes battery capacity, renewable supply and dc power as input dataframes
# and calculates how much battery can increase renewable coverage
# returns the non renewable amount that battery cannot cover
def apply_battery(battery_capacity, df_ren, df_dc_pow):
    b = Battery2(battery_capacity, battery_capacity)
    tot_non_ren_mw = 0 # store the mw amount battery cannot supply here

    for i in range(df_dc_pow.shape[0]):
        ren_mw = df_ren[i]
        df_dc = df_dc_pow["avg_dc_power_mw"][i]
        gap = df_dc - ren_mw
        # lack or excess renewable supply
        if gap > 0: #discharging from battery
            discharged_amount = b.discharge(gap)
            tot_non_ren_mw = tot_non_ren_mw + gap - discharged_amount
        else: # charging the battery
            b.charge(-gap)

    return tot_non_ren_mw

