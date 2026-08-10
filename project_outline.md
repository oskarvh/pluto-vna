# Project outline

I have a ADALM-PLUTO SDR connected via USB to the computer. 
I have modded the pluto SDR to access the two extra RX and TX ports, and I have the following setup:

```
                                   ______________
_______________                    | 2.5-6 GHz  |
|         TX2-|-[NC]               | Splitter   |
| Pluto   TX1-|--[8db Attenuator]--|-IN         |
| SDR     RX1-|--------------------|-CPL        |
|         RX2-|---------[DUT]------|-OUT        |
|_____________|                    |____________|
```

Meaning, S12 can be measured from TX1 to RX2, S11 from TX1 to RX1. 

## Hardware
The DUTs available are:
- Open
- Short
- 50 ohm termination (to ground)
- Attenuators
- throughline (0db attenuator)

These can be re-used for calibration purposes. 

The hardware is:
- Splitter: mini circuits ZADC-10-63-S+. 
- Attenuator: Mini-circuits 15542 8dB attenuator.
- Mini circuits ZAPD-4 power splitter (not connected).

ADALM-PLUTO SDR with the two extra ports added. No other firmware modifications have been made to my knowledge.

## Goal
To have a GUI that communicates with the Pluto SDR, enabling SDR functionality. I want both a linear absolute amplitude and phase and a smith chart over the frequency range. 

The aim is to use this to characterize RF circuits (maximum 2 port systems). 

# Future work
I would love to be able to measure S21 and S22, and I have a power splitter that may be able to help. However, I want to first solve the S12/S11 case. 

Please provide a hardware setup for the Pluto SDR to be able to measure S21/S22 parameters. 

# Project outline

Create a todo list in a readme (.md) format to track the work, and make it clear to a human reader what the outline is, what is done and what is left. 
Keep this todo list at a high level, ergo short, such that it's easy to get a quick glance. Create any other longer scratch files or todo lists separate from this, or appended at the bottom, as long as I can get a quick status update on the project without reading a lengthy report. 

This repo is a new repo aimed to track this work. 