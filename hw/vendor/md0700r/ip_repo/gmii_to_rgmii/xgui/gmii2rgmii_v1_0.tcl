# Definitional proc to organize widgets for parameters.
proc init_gui { IPINST } {
  ipgui::add_param $IPINST -name "Component_Name"
  #Adding Page
  ipgui::add_page $IPINST -name "Page 0"


}

proc update_PARAM_VALUE.IDELAY_VALUE { PARAM_VALUE.IDELAY_VALUE } {
	# Procedure called to update IDELAY_VALUE when any of the dependent parameters in the arguments change
}

proc validate_PARAM_VALUE.IDELAY_VALUE { PARAM_VALUE.IDELAY_VALUE } {
	# Procedure called to validate IDELAY_VALUE
	return true
}


proc update_MODELPARAM_VALUE.IDELAY_VALUE { MODELPARAM_VALUE.IDELAY_VALUE PARAM_VALUE.IDELAY_VALUE } {
	# Procedure called to set VHDL generic/Verilog parameter value(s) based on TCL parameter value
	set_property value [get_property value ${PARAM_VALUE.IDELAY_VALUE}] ${MODELPARAM_VALUE.IDELAY_VALUE}
}

