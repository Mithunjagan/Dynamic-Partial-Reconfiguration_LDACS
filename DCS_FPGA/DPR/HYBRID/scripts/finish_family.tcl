# Resume from preserved routed checkpoints; never change the locked static design.
proc ldacs_validate_configuration {out module} {
    report_drc -file $out/${module}_drc.rpt
    set failures [get_drc_violations -quiet -filter {SEVERITY == Error || SEVERITY == "Critical Warning"}]
    if {[llength $failures]} {error "DRC failed for $module: $failures"}
    report_route_status -file $out/${module}_route.rpt
    report_timing_summary -file $out/${module}_timing.rpt
    report_utilization -file $out/${module}_utilization.rpt
    report_utilization -hierarchical -file $out/${module}_hierarchy.rpt
    foreach type {max min} {
        set paths [get_timing_paths -quiet -delay_type $type -max_paths 1]
        if {![llength $paths] || [get_property SLACK [lindex $paths 0]]<0} {
            error "Missing or failing $type timing for $module"
        }
    }
}
proc ldacs_finish_family {} {
    global argv
    set root [file normalize [lindex $argv 0]]
    set build $root/hw/vivado/build_dpr
    set out $build/dfx
    set f [open $build/build_token.txt r];set token [string trim [read $f]];close $f
    set f [open $build/source_snapshot.sha256 r];set source_sha [string trim [read $f]];close $f
    open_checkpoint $out/full_pl_routed.dcp
    set cells [get_cells -hier -filter {HD.RECONFIGURABLE == 1}]
    if {[llength $cells]!=1} {error "Expected exactly one RP"}
    set rp_cell [get_property NAME [lindex $cells 0]]
    ldacs_validate_configuration $out full_pl
    write_xdc -force $out/implemented_constraints.xdc
    close_design
    foreach module {hybrid blank anchor} {
        if {[file exists $out/${module}_routed.dcp]} {
            open_checkpoint $out/${module}_routed.dcp
        } else {
            open_checkpoint $out/static_locked.dcp
            read_checkpoint -cell $rp_cell $out/${module}_synth.dcp
            opt_design
            place_design
            route_design
            ldacs_validate_configuration $out $module
            write_checkpoint -force $out/${module}_routed.dcp
        }
        ldacs_validate_configuration $out $module
        pr_verify -full_check -file $out/${module}_pr_verify.rpt $out/full_pl_routed.dcp $out/${module}_routed.dcp
        write_bitstream -force -bin_file $out/${module}.bit
        write_bitstream -force -bin_file -cell $rp_cell $out/${module}_partial.bit
        close_design
    }
    set f [open $out/routed_manifest.json w]
    puts $f [format { {"schema":"ldacs_dfx_routed_v1","part":"xc7z010clg400-1","build_token":%s,"rp_cell":"%s","pr_verify_passed":true,"critical_warnings_passed":true,"static_monitor_version":1,"hardware_source_sha256":"%s","configurations":["full_pl","hybrid","blank","anchor"]} } $token $rp_cell $source_sha]
    close $f
    puts DFX_RESUMED_FAMILY_VERIFIED
}
ldacs_finish_family
exit
