# Include actual synthesis/implementation results and all referenced sources.
if {[llength $argv]!=2} {error "project.xpr new_archive.zip"}
lassign $argv project archive
if {[file exists $archive]} {error "Archive exists; choose a new filename"}
open_project $project
# Vivado's default .Xil/PrjAr path exceeds Windows MAX_PATH for planner IP.
# archive_project empties its temporary directory: use a fresh, bounded path.
set temporary [file normalize "C:/fpga_build/la_arc_[pid]"]
if {[file dirname $temporary] ne [file normalize "C:/fpga_build"] || [file exists $temporary]} {
    error "Refusing to reuse an archive temporary directory"
}
archive_project $archive -include_config_settings -temp_dir $temporary
close_project
puts "LINEART_VIVADO_ARCHIVE_COMPLETE"
