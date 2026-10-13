<?php
/**
 * EaglePCBView3D - Web renderer for EAGLE .brd / .sch files (XML format).
 * Script: eagle_pcb_view_3d.php
 * Version 1.2 (2026-10-13)
 */

// ----------------------------------------------------------------- palette / layers
$PALETTE = [
    1 => "#3c3cf0", 2 => "#32b432", 3 => "#00b4b4", 4 => "#d23232", 5 => "#b432b4",
    6 => "#b4b400", 7 => "#d2d2d2", 8 => "#787878", 9 => "#6e6eff", 10 => "#6ee66e",
    11 => "#6ee6e6", 12 => "#ff7878", 13 => "#ff78ff", 14 => "#ffff50", 15 => "#c8c828",
    16 => "#aaaaaa",
];

$MIRROR_LAYERS = [
    1 => 16, 16 => 1, 21 => 22, 22 => 21, 23 => 24, 24 => 23, 25 => 26, 26 => 25,
    27 => 28, 28 => 27, 29 => 30, 30 => 29, 31 => 32, 32 => 31, 33 => 34, 34 => 33,
    35 => 36, 36 => 35, 37 => 38, 38 => 37, 39 => 40, 40 => 39, 41 => 42, 42 => 41,
    51 => 52, 52 => 51,
];

$BOARD_ORDER = [16, 1, 17, 18, 45, 46, 22, 21, 52, 51, 26, 25, 28, 27, 20];
$SCH_ORDER   = [94, 93, 91, 92, 95, 96, 97, 98];

$PIN_LEN = ["point" => 0.0, "short" => 2.54, "middle" => 5.08, "long" => 7.62];

$DASH = [
    "longdash"  => "5.08 1.27",
    "shortdash" => "2.032 1.016",
    "dashdot"   => "5.08 1.27 0.508 1.27",
];

$FILL_PATTERNS = [
    2 => ["/", 0.5], 3 => ["/", 0.8], 4 => ["\\", 0.8], 5 => ["-", 0.8],
    6 => ["\\", 0.5], 7 => ["|", 0.8], 8 => ["/", 1.6], 9 => ["-", 0.5],
    10 => ["/", 1.2], 11 => ["x", 1.0],
];
$FILL_PX = [2 => 4, 3 => 6, 4 => 6, 5 => 6, 6 => 4, 7 => 6, 8 => 8, 9 => 4, 10 => 8, 11 => 8];

$KEEPOUT_RESTRICT = [39, 40, 41, 42, 43];
$KEEPOUT_RESTRICT_WIDTH = 0.3;

$BOARD_THICKNESS = 1.6;

$TOP_LAYERS    = [1, 21, 23, 25, 27, 29, 31, 33, 35, 37, 39, 41, 51, 53];
$BOTTOM_LAYERS = [16, 22, 24, 26, 28, 30, 32, 34, 36, 38, 40, 42, 52, 54];

$UNIT_MM = [
    "" => 1.0, "mm" => 1.0, "mil" => 0.0254, "inch" => 25.4,
    "in" => 25.4, "micron" => 0.001, "um" => 0.001,
];

$VARS = [];
$DESIGN_RULES = [];
$WARN_SEEN = [];

// ----------------------------------------------------------------- helpers
function warn($msg) {
    global $WARN_SEEN;
    if (!isset($WARN_SEEN[$msg])) {
        $WARN_SEEN[$msg] = true;
        error_log("warning: " . $msg);
    }
}

function num($el, $key, $default = 0.0) {
    if (!($el instanceof SimpleXMLElement)) return $default;
    $v = $el[$key] ?? null;
    if ($v === null || (string)$v === "") return $default;
    return (float)$v;
}

function parse_rot($s) {
    if ($s === null) $s = "R0";
    $s = (string)$s;
    if (preg_match('/^(S?)(M?)R(-?[\d.]+)$/', $s, $m)) {
        return [$m[2] === 'M', $m[1] === 'S', (float)$m[3]];
    }
    return [false, false, 0.0];
}

// ----------------------------------------------------------------- class Tf
class Tf {
    public $x, $y, $rot, $m;
    public $c, $s;
    function __construct($x = 0.0, $y = 0.0, $rot = 0.0, $mirror = false) {
        $this->x = $x; $this->y = $y; $this->rot = $rot; $this->m = $mirror;
        $r = deg2rad($rot);
        $this->c = cos($r); $this->s = sin($r);
    }
    function pt($x, $y) {
        if ($this->m) $x = -$x;
        return [$x * $this->c - $y * $this->s + $this->x,
                $x * $this->s + $y * $this->c + $this->y];
    }
}

function rect_pts($cx, $cy, $w, $h, $rot = 0.0) {
    $r = deg2rad($rot); $c = cos($r); $s = sin($r);
    $pts = [];
    foreach ([[-$w/2, -$h/2], [$w/2, -$h/2], [$w/2, $h/2], [-$w/2, $h/2]] as $d) {
        $pts[] = [$cx + $d[0]*$c - $d[1]*$s, $cy + $d[0]*$s + $d[1]*$c];
    }
    return $pts;
}

function rrect_pts($cx, $cy, $w, $h, $rot, $rad, $steps = 6) {
    $rad = min($rad, $w/2, $h/2);
    if ($rad <= 1e-6) return rect_pts($cx, $cy, $w, $h, $rot);
    $pts = [];
    $corners = [
        [$w/2 - $rad,  $h/2 - $rad,   0],
        [-$w/2 + $rad, $h/2 - $rad,  90],
        [-$w/2 + $rad, -$h/2 + $rad, 180],
        [$w/2 - $rad,  -$h/2 + $rad, 270],
    ];
    foreach ($corners as $co) {
        for ($i = 0; $i <= $steps; $i++) {
            $a = deg2rad($co[2] + 90.0 * $i / $steps);
            $pts[] = [$co[0] + $rad * cos($a), $co[1] + $rad * sin($a)];
        }
    }
    $r = deg2rad($rot); $c = cos($r); $s = sin($r);
    $out = [];
    foreach ($pts as $p) {
        $out[] = [$cx + $p[0]*$c - $p[1]*$s, $cy + $p[0]*$s + $p[1]*$c];
    }
    return $out;
}

function markup($txt) {
    if (strpos($txt, '!') === false) return htmlspecialchars($txt, ENT_QUOTES | ENT_XML1);
    $out = []; $over = false;
    foreach (explode('!', $txt) as $part) {
        if ($part !== '') {
            $esc = htmlspecialchars($part, ENT_QUOTES | ENT_XML1);
            $out[] = $over ? '<tspan text-decoration="overline">' . $esc . '</tspan>' : $esc;
        }
        $over = !$over;
    }
    return implode('', $out);
}

function arc_seg($p1, $p2, $curve) {
    if (abs($curve) <= 0.01 || ($p1[0] === $p2[0] && $p1[1] === $p2[1])) {
        return sprintf("L%.4f,%.4f", $p2[0], -$p2[1]);
    }
    $chord = sqrt(($p1[0]-$p2[0])**2 + ($p1[1]-$p2[1])**2);
    $th = deg2rad(min(abs($curve), 359.9));
    $r = $chord / (2 * sin($th / 2));
    $large = $th > M_PI ? 1 : 0;
    $sweep = $curve > 0 ? 0 : 1;
    return sprintf("A%.4f,%.4f 0 %d %d %.4f,%.4f", $r, $r, $large, $sweep, $p2[0], -$p2[1]);
}

function expand_vars($txt, $subst = null) {
    global $VARS;
    if (strpos($txt, '>') === false) return $txt;
    $table = $VARS;
    if ($subst) $table = array_merge($table, $subst);
    return preg_replace_callback('/>([A-Za-z_][A-Za-z0-9_]*)/', function ($m) use ($table) {
        $k = strtoupper($m[1]);
        return $table[$k] ?? $m[0];
    }, $txt);
}

// ----------------------------------------------------------------- class Canvas
class Canvas {
    public $layers;
    public $items = [];
    public $bbox = [1e9, 1e9, -1e9, -1e9];
    public $no_mirror_text = false;
    public $outline_segs = [];
    public $outline_circles = [];
    public $drills = [];
    public $extra = [];

    function __construct($layers) { $this->layers = $layers; }

    function _bb($x, $y, $m = 0.0) {
        $b = &$this->bbox;
        $b[0] = min($b[0], $x - $m); $b[1] = min($b[1], $y - $m);
        $b[2] = max($b[2], $x + $m); $b[3] = max($b[3], $y + $m);
    }

    function add($layer, $s) {
        if (!isset($this->items[$layer])) $this->items[$layer] = [];
        $this->items[$layer][] = $s;
    }

    function wire($layer, $p1, $p2, $w, $curve = 0.0, $cap = "round", $style = null) {
        global $DASH;
        if ($w <= 0) $w = max($w, 0.1);
        $this->_bb($p1[0], $p1[1], $w/2);
        $this->_bb($p2[0], $p2[1], $w/2);
        $a = sprintf("%.4f,%.4f", $p1[0], -$p1[1]);
        $b = sprintf("%.4f,%.4f", $p2[0], -$p2[1]);
        $d = "M$a " . arc_seg($p1, $p2, $curve);
        if (abs($curve) > 0.01 && ($p1[0] !== $p2[0] || $p1[1] !== $p2[1])) {
            $chord = sqrt(($p1[0]-$p2[0])**2 + ($p1[1]-$p2[1])**2);
            $th = deg2rad(min(abs($curve), 359.9));
            $r = $chord / (2 * sin($th / 2));
            $mx = ($p1[0]+$p2[0])/2; $my = ($p1[1]+$p2[1])/2;
            $sag = $th <= M_PI ? $r*(1-cos($th/2)) : $r*(1+cos(M_PI-$th/2));
            $nx = -($p2[1]-$p1[1])/$chord; $ny = ($p2[0]-$p1[0])/$chord;
            $sgn = $curve > 0 ? 1 : -1;
            $this->_bb($mx - $sgn*$nx*$sag, $my - $sgn*$ny*$sag, $w/2);
        }
        $dash = ($style && isset($DASH[$style])) ? ' stroke-dasharray="' . $DASH[$style] . '"' : "";
        if ($dash) $cap = "butt";
        $this->add($layer, sprintf(
            '<path d="%s" fill="none" stroke="currentColor" stroke-width="%.4f" stroke-linecap="%s"%s/>',
            $d, $w, $cap, $dash));
    }

    function poly($layer, $pts, $fill = true, $w = 0.0, $opacity = 1.0, $curves = null) {
        if (count($pts) < 2) return;
        foreach ($pts as $p) $this->_bb($p[0], $p[1], $w/2);
        if ($curves) {
            $has_curve = false;
            foreach ($curves as $c) if (abs($c) > 0.01) { $has_curve = true; break; }
        } else $has_curve = false;
        if ($has_curve) {
            $d = sprintf("M%.4f,%.4f", $pts[0][0], -$pts[0][1]);
            for ($i = 0; $i < count($pts); $i++) {
                $c = $curves[$i] ?? 0;
                $d .= " " . arc_seg($pts[$i], $pts[($i+1) % count($pts)], $c);
            }
            $d .= " Z";
        } else {
            $parts = [];
            foreach ($pts as $p) $parts[] = sprintf("%.4f,%.4f", $p[0], -$p[1]);
            $d = "M" . implode(" L", $parts) . " Z";
        }
        $st = $fill ? 'fill="currentColor"' : 'fill="none"';
        if ($fill && $opacity < 1) $st .= sprintf(' fill-opacity="%.2f"', $opacity);
        if ($w > 0) $st .= sprintf(' stroke="currentColor" stroke-width="%.4f" stroke-linejoin="round"', $w);
        $this->add($layer, sprintf('<path d="%s" %s/>', $d, $st));
    }

    function circle($layer, $c, $r, $w = 0.0, $fill = null, $color = null, $cls = null) {
        $this->_bb($c[0], $c[1], $r + $w/2);
        $filled = $fill !== null ? $fill : ($w <= 0);
        $col = $color ?: "currentColor";
        $ca = $cls ? ' class="' . $cls . '"' : "";
        if ($filled) {
            $this->add($layer, sprintf(
                '<circle cx="%.4f" cy="%.4f" r="%.4f" fill="%s"%s/>',
                $c[0], -$c[1], $r, $col, $ca));
        } else {
            $this->add($layer, sprintf(
                '<circle cx="%.4f" cy="%.4f" r="%.4f" fill="none" stroke="%s" stroke-width="%.4f"%s/>',
                $c[0], -$c[1], $r, $col, $w, $ca));
        }
    }

    function text($layer, $x, $y, $size, $ang, $txt, $align = "bottom-left",
                  $mirror = false, $spin = false, $dist = 50.0, $fit = true) {
        if (!$txt) return;
        $lines = explode("\n", $txt);
        if ($this->no_mirror_text) $mirror = false;
        $ang = fmod($ang, 360.0); if ($ang < 0) $ang += 360.0;
        $parts = explode('-', $align ?: "bottom-left");
        if ($parts === ["center"]) { $v = "center"; $h = "center"; }
        else { $v = $parts[0]; $h = $parts[1] ?? "left"; }
        if (!$spin && $ang > 90.0 && $ang <= 270.0) {
            $ang = fmod($ang + 180.0, 360.0);
            $h = ["left" => "right", "right" => "left"][$h] ?? $h;
            $v = ["top" => "bottom", "bottom" => "top"][$v] ?? $v;
        }
        $anchor = ["left" => "start", "center" => "middle", "right" => "end"][$h];
        if ($mirror) $anchor = ["start" => "end", "end" => "start"][$anchor] ?? $anchor;
        $pitch = $size * (1.0 + $dist / 100.0);
        $block = (count($lines) - 1) * $pitch;
        $first = ["bottom" => -$block, "center" => -$block/2 + 0.5*$size, "top" => $size][$v];
        $maxlen = 0;
        foreach ($lines as $l) {
            $len = max(strlen(str_replace('!', '', $l)), 1) * $size * 0.62;
            if ($len > $maxlen) $maxlen = $len;
        }
        $ar = deg2rad($ang);
        $this->_bb($x, $y, $size * 0.5);
        if ($fit) $this->_bb($x + $maxlen*cos($ar), $y + $maxlen*sin($ar), $size*0.5 + $block);
        $tr = sprintf("translate(%.4f,%.4f) rotate(%.3f)%s",
                      $x, -$y, -$ang, $mirror ? " scale(-1,1)" : "");
        $spans = [];
        foreach ($lines as $k => $ln) {
            $ln_len = max(strlen(str_replace('!', '', $ln)), 1) * $size * 0.62;
            $content = $ln ? markup($ln) : "&#160;";
            $spans[] = sprintf(
                '<tspan x="0" y="%.4f" textLength="%.4f" lengthAdjust="spacingAndGlyphs">%s</tspan>',
                $first + $k * $pitch, $ln_len, $content);
        }
        $this->add($layer, sprintf(
            '<text transform="%s" font-family="DejaVu Sans Mono,Consolas,monospace" ' .
            'font-size="%.4f" text-anchor="%s" fill="currentColor">%s</text>',
            $tr, $size * 1.25, $anchor, implode('', $spans)));
    }
}

// ----------------------------------------------------------------- parsing
// Children of $el->$parent->$child, or an empty array when $parent is missing (avoids foreach() on null)
function kids($el, $parent, $child) {
    if ($el === null || !isset($el->$parent)) return [];
    return $el->$parent->$child ?? [];
}

function parse_layers($drawing) {
    $out = [];
    foreach (kids($drawing, 'layers', 'layer') as $l) {
        $n = (int)$l['number'];
        $out[$n] = [
            'name'    => (string)$l['name'],
            'color'   => (int)($l['color'] ?? 7),
            'visible' => ((string)$l['visible']) === 'yes',
            'fill'    => (int)($l['fill'] ?? 1),
        ];
    }
    return $out;
}

function parse_libs($libs_el) {
    $out = [];
    if ($libs_el === null) return $out;
    $libraries = $libs_el->library ?? [];
    foreach ($libraries as $lib) {
        $L = ['packages' => [], 'symbols' => [], 'gates' => [], 'addlevel' => [], 'devmap' => []];
        $pk = $lib->packages ?? null;
        if ($pk) foreach ($pk->package as $p) $L['packages'][(string)$p['name']] = $p;
        $sy = $lib->symbols ?? null;
        if ($sy) foreach ($sy->symbol as $s) $L['symbols'][(string)$s['name']] = $s;
        $ds = $lib->devicesets ?? null;
        if ($ds) foreach ($ds->deviceset as $d) {
            $n = (string)$d['name'];
            $L['gates'][$n] = [];
            $L['addlevel'][$n] = [];
            foreach (kids($d, 'gates', 'gate') as $g) {
                $gn = (string)$g['name'];
                $L['gates'][$n][$gn] = (string)$g['symbol'];
                $L['addlevel'][$n][$gn] = (string)($g['addlevel'] ?? 'next');
            }
            foreach (kids($d, 'devices', 'device') as $dv) {
                $dn = (string)($dv['name'] ?? '');
                $L['devmap'][$n . '|' . $dn] = [];
                foreach (kids($dv, 'connects', 'connect') as $c) {
                    $L['devmap'][$n . '|' . $dn][(string)$c['gate'] . '|' . (string)$c['pin']] = (string)$c['pad'];
                }
            }
        }
        $urn = (string)($lib['urn'] ?? '');
        $name = (string)$lib['name'];
        $out[$name . '|' . $urn] = $L;
        if (!isset($out[$name])) $out[$name] = $L;
    }
    return $out;
}

function find_lib($libs, $el) {
    $name = (string)$el['library'];
    $urn  = (string)($el['library_urn'] ?? '');
    $key = $name . '|' . $urn;
    if (isset($libs[$key])) return $libs[$key];
    return $libs[$name] ?? null;
}

function parse_design_rules($board) {
    global $DESIGN_RULES, $UNIT_MM;
    $DESIGN_RULES = [];
    $dr = $board->designrules ?? null;
    if (!$dr) return;
    foreach ($dr->param as $pm) {
        $name = (string)$pm['name'];
        $val  = (string)$pm['value'];
        if (preg_match('/^\s*(-?[\d.]+)\s*([a-zA-Z]*)\s*$/', $val, $m)) {
            if (strpos($name, 'rv') === 0) {
                $DESIGN_RULES[$name] = (float)$m[1];
            } elseif (strpos($name, 'rl') === 0) {
                $u = strtolower($m[2]);
                $DESIGN_RULES[$name] = (float)$m[1] * ($UNIT_MM[$u] ?? 1.0);
            }
        }
    }
}

function pad_dia($drill, $dia, $kind = "PadTop") {
    global $DESIGN_RULES;
    if ($dia) return $dia;
    $rv = $DESIGN_RULES['rv' . $kind] ?? 0.25;
    $lo = $DESIGN_RULES['rlMin' . $kind] ?? 0.254;
    $hi = $DESIGN_RULES['rlMax' . $kind] ?? 0.508;
    return $drill + 2 * min(max($drill * $rv, $lo), $hi);
}

// ----------------------------------------------------------------- drawing
function missing_marker(&$cv, $x, $y, $name) {
    $cv->poly(94, rect_pts($x, $y, 5.08, 5.08), false, 0.15);
    $cv->wire(94, [$x-2.54, $y-2.54], [$x+2.54, $y+2.54], 0.15);
    $cv->wire(94, [$x-2.54, $y+2.54], [$x+2.54, $y-2.54], 0.15);
    $cv->text(95, $x, $y + 3.2, 1.27, 0.0, $name . " (missing)", "bottom-center");
}

function draw_common(&$cv, $ch, $tf, $ml, $subst = null, $skip_dyn = false, $pour = false) {
    global $MIRROR_LAYERS;
    $t = $ch->getName();
    if ($t === 'wire') {
        $L = $ml((int)$ch['layer']);
        $p1 = $tf->pt(num($ch, 'x1'), num($ch, 'y1'));
        $p2 = $tf->pt(num($ch, 'x2'), num($ch, 'y2'));
        $curve = num($ch, 'curve');
        $cv->wire($L, $p1, $p2, num($ch, 'width'),
                  $tf->m ? -$curve : $curve,
                  ((string)$ch['cap']) === 'flat' ? 'flat' : 'round',
                  (string)($ch['style'] ?? ''));
        if ($L === 20) $cv->outline_segs[] = [$p1, $p2, $tf->m ? -$curve : $curve];
    } elseif ($t === 'rectangle') {
        $L = $ml((int)$ch['layer']);
        $x1 = num($ch, 'x1'); $y1 = num($ch, 'y1');
        $x2 = num($ch, 'x2'); $y2 = num($ch, 'y2');
        $rot = parse_rot($ch['rot'] ?? null)[2];
        $pts = rect_pts(($x1+$x2)/2, ($y1+$y2)/2, abs($x2-$x1), abs($y2-$y1), $rot);
        $mapped = [];
        foreach ($pts as $p) $mapped[] = $tf->pt($p[0], $p[1]);
        $cv->poly($L, $mapped);
        if ($L === 20) for ($k = 0; $k < 4; $k++) $cv->outline_segs[] = [$mapped[$k], $mapped[($k + 1) % 4], 0.0];
    } elseif ($t === 'circle') {
        $L = $ml((int)$ch['layer']);
        $cc = $tf->pt(num($ch, 'x'), num($ch, 'y'));
        $cv->circle($L, $cc, num($ch, 'radius'), num($ch, 'width'));
        if ($L === 20) $cv->outline_circles[] = [$cc, num($ch, 'radius')];
    } elseif ($t === 'polygon') {
        $L = $ml((int)$ch['layer']);
        $vs = $ch->vertex ?? [];
        $pts = [];
        foreach ($vs as $v) $pts[] = $tf->pt(num($v, 'x'), num($v, 'y'));
        $curves = [];
        foreach ($vs as $v) $curves[] = $tf->m ? -num($v, 'curve') : num($v, 'curve');
        $w = num($ch, 'width');
        if ($pour) $cv->poly($L, $pts, true, max($w, 0.1), 0.35, $curves);
        else       $cv->poly($L, $pts, true, $w, 1.0, $curves);
        if ($L === 20 && count($pts) >= 3) {
            for ($k = 0; $k < count($pts); $k++) $cv->outline_segs[] = [$pts[$k], $pts[($k + 1) % count($pts)], $curves[$k] ?? 0.0];
        }
    } elseif ($t === 'hole') {
        $hc = $tf->pt(num($ch, 'x'), num($ch, 'y'));
        $hr = num($ch, 'drill') / 2;
        $cv->circle(45, $hc, $hr, 0, true, "#000");
        $cv->circle(45, $hc, $hr, 0.1, false, null, "hr");
        $cv->drills[] = [$hc, $hr, 45];
    } elseif ($t === 'text') {
        $txt = trim((string)$ch);
        if (in_array(strtoupper($txt), [">NAME", ">VALUE"]) && $skip_dyn) return true;
        $txt = expand_vars($txt, $subst);
        $L = $ml((int)$ch['layer']);
        [$tm, $ts, $r] = parse_rot($ch['rot'] ?? null);
        $ang = $tf->rot + ($tf->m ? (180.0 - $r) : $r);
        [$x, $y] = $tf->pt(num($ch, 'x'), num($ch, 'y'));
        $cv->text($L, $x, $y, num($ch, 'size', 1.27), $ang, $txt,
                  (string)($ch['align'] ?? 'bottom-left'),
                  $tf->m !== $tm, $ts, num($ch, 'distance', 50.0));
    } else {
        return false;
    }
    return true;
}

function draw_element(&$cv, $el, $libs) {
    global $MIRROR_LAYERS;
    [$m, $_spin, $a] = parse_rot($el['rot'] ?? null);
    $tf = new Tf(num($el, 'x'), num($el, 'y'), $a, $m);
    $lib = find_lib($libs, $el) ?: ['packages' => []];
    $pkg_name = (string)$el['package'];
    $pkg = $lib['packages'][$pkg_name] ?? null;
    if ($pkg === null) {
        $lname = (string)$el['library'];
        $why = find_lib($libs, $el) === null
            ? "library '$lname' not present in the file"
            : "library '$lname' has no package '$pkg_name'";
        warn((string)$el['name'] . ": " . $why);
        missing_marker($cv, $tf->x, $tf->y, (string)$el['name']);
        return;
    }
    $smashed = ((string)$el['smashed']) === 'yes';
    $name = (string)$el['name'];
    $value = (string)$el['value'];
    $subst = ['NAME' => $name, 'VALUE' => $value];
    
    // FIX: Use xpath instead of direct property access
    $attributes = $el->xpath('attribute') ?: [];
    foreach ($attributes as $at) {
        $an = strtoupper((string)$at['name']);
        if (isset($at['value']) && !isset($subst[$an])) {
            $subst[$an] = (string)$at['value'];
        }
    }
    
    $ml = function ($n) use ($m, $MIRROR_LAYERS) {
        return ($m && isset($MIRROR_LAYERS[$n])) ? $MIRROR_LAYERS[$n] : $n;
    };
    foreach ($pkg->children() as $ch) {
        $tag = $ch->getName();
        if ($tag === 'smd') {
            $L = $ml((int)($ch['layer'] ?? 1));
            $rr = num($ch, 'roundness') / 100.0;
            $dx = num($ch, 'dx'); $dy = num($ch, 'dy');
            $rot = parse_rot($ch['rot'] ?? null)[2];
            $pts = rrect_pts(num($ch, 'x'), num($ch, 'y'), $dx, $dy, $rot, $rr * min($dx, $dy) / 2);
            $mapped = [];
            foreach ($pts as $p) $mapped[] = $tf->pt($p[0], $p[1]);
            $cv->poly($L, $mapped);
            $smd_key = "smd|" . $L;
            if (!isset($cv->extra[$smd_key])) $cv->extra[$smd_key] = [];
            $cv->extra[$smd_key][] = end($cv->items[$L]);
        } elseif ($tag === 'pad') {
            $drill = num($ch, 'drill');
            $dia = pad_dia($drill, num($ch, 'diameter'));
            $c = $tf->pt(num($ch, 'x'), num($ch, 'y'));
            $shape = (string)($ch['shape'] ?? 'round');
            $pr = parse_rot($ch['rot'] ?? null)[2];
            $cx = num($ch, 'x'); $cy = num($ch, 'y');
            $pts = null;
            if ($shape === 'square') {
                $pts = rect_pts($cx, $cy, $dia, $dia, $pr);
            } elseif ($shape === 'octagon') {
                $pts = [];
                for ($k = 0; $k < 8; $k++) {
                    $ang = deg2rad($pr + 22.5 + 45 * $k);
                    $pts[] = [$cx + $dia/2/cos(M_PI/8)*cos($ang),
                              $cy + $dia/2/cos(M_PI/8)*sin($ang)];
                }
            } elseif ($shape === 'long' || $shape === 'offset') {
                $length = $dia * 2.0;
                $off = $shape === 'offset' ? $dia/2 : 0.0;
                $r = deg2rad($pr);
                $pts = rrect_pts($cx + $off*cos($r), $cy + $off*sin($r),
                                 $length, $dia, $pr, $dia/2);
            }
            if ($pts) {
                $mapped = [];
                foreach ($pts as $p) $mapped[] = $tf->pt($p[0], $p[1]);
                $cv->poly(17, $mapped);
            } else {
                $cv->circle(17, $c, $dia/2, 0, true);
            }
            $cv->circle(17, $c, $drill/2, 0, true, "#000");
            $cv->drills[] = [$c, $drill/2, 17];
        } else {
            draw_common($cv, $ch, $tf, $ml, $subst, $smashed);
        }
    }
    if ($smashed) {
        // FIX: Use xpath instead of direct property access
        $attributes = $el->xpath('attribute') ?: [];
        foreach ($attributes as $at) {
            if (!isset($at['x']) || (string)$at['display'] === 'off') continue;
            $an = strtoupper((string)$at['name']);
            $txt = $an === 'NAME' ? $name : ($an === 'VALUE' ? $value : (string)$at['value']);
            [$tm, $ts, $r] = parse_rot($at['rot'] ?? null);
            $cv->text((int)($at['layer'] ?? 25), num($at, 'x'), num($at, 'y'),
                      num($at, 'size', 1.27), $r, $txt,
                      (string)($at['align'] ?? 'bottom-left'), $tm, $ts);
        }
    }
}

function render_board($root) {
    $drawing = $root->drawing;
    $layers = parse_layers($drawing);
    $board = $drawing->board;
    $libs = parse_libs($board->libraries ?? null);
    parse_design_rules($board);
    $cv = new Canvas($layers);
    $ident = new Tf();
    $plain = $board->plain ?? null;
    if ($plain) {
        foreach ($plain->children() as $ch) {
            draw_common($cv, $ch, $ident, function ($n) { return $n; });
        }
    }
    $els = $board->elements ?? null;
    if ($els) foreach ($els->element as $el) draw_element($cv, $el, $libs);
    $sigs = $board->signals ?? null;
    if ($sigs) {
        foreach ($sigs->signal as $sig) {
            foreach ($sig->children() as $ch) {
                $tag = $ch->getName();
                if ($tag === 'via') {
                    $drill = num($ch, 'drill');
                    $dia = pad_dia($drill, num($ch, 'diameter'), 'ViaOuter');
                    $c = [num($ch, 'x'), num($ch, 'y')];
                    $cv->circle(18, $c, $dia/2, 0, true);
                    $cv->circle(18, $c, $drill/2, 0, true, "#000");
                    $cv->drills[] = [$c, $drill/2, 18];
                } elseif ($tag === 'wire' || $tag === 'polygon') {
                    draw_common($cv, $ch, $ident, function ($n) { return $n; }, null, false, true);
                }
            }
        }
    }
    return [["", $cv, $GLOBALS['BOARD_ORDER']]];
}

function draw_xref_flag(&$cv, $layer, $x, $y, $size, $rot, $name) {
    [$m, $_s, $a] = parse_rot($rot);
    $t = new Tf(0, 0, $a, $m);
    $d = $t->pt(1, 0); $n = $t->pt(0, 1);
    $h = $size * 1.3; $mg = $size * 0.4;
    $length = $h/2 + $mg + max(strlen(str_replace('!', '', $name)), 1) * $size * 0.62 + $mg;
    $P = function ($u, $v) use ($x, $y, $d, $n) {
        return [$x + $d[0]*$u + $n[0]*$v, $y + $d[1]*$u + $n[1]*$v];
    };
    $cv->poly($layer, [
        $P(0, 0), $P($h/2, $h/2), $P($length, $h/2),
        $P($length, -$h/2), $P($h/2, -$h/2)
    ], false, 0.2);
    [$sx, $sy] = $P($h/2 + $mg, 0);
    $cv->text($layer, $sx, $sy, $size, rad2deg(atan2($d[1], $d[0])), $name, "center-left");
}

function draw_pin(&$cv, $pin, $tf, $pads) {
    global $PIN_LEN;
    $x = num($pin, 'x'); $y = num($pin, 'y');
    $len_key = (string)($pin['length'] ?? 'long');
    $ln = $PIN_LEN[$len_key] ?? 7.62;
    [$m, $_s, $r] = parse_rot($pin['rot'] ?? null);
    $rr = deg2rad($r);
    $dx = cos($rr); $dy = sin($rr);
    $p0 = $tf->pt($x, $y);
    $p1 = $tf->pt($x + $dx*$ln, $y + $dy*$ln);
    $cv->wire(94, $p0, $p1, 0.1524);
    $cv->circle(93, $p0, 0.25, 0, true);
    $vis = (string)($pin['visible'] ?? 'both');
    $name = preg_replace('/@\d+$/', '', (string)$pin['name']);
    $vert = abs($dy) > 0.5;
    $ang_local = $vert ? 90.0 : 0.0;
    if (in_array($vis, ['pin', 'both']) && $name) {
        $inward = $dx > 0.5 || $dy > 0.5;
        $ex = $x + $dx*($ln + 0.762); $ey = $y + $dy*($ln + 0.762);
        $al = $inward ? "center-left" : "center-right";
        [$tx, $ty] = $tf->pt($ex, $ey);
        $cv->text(95, $tx, $ty, 1.778,
                  $tf->rot + ($tf->m ? (180 - $ang_local) : $ang_local),
                  $name, $al, $tf->m);
    }
    if (in_array($vis, ['pad', 'both'])) {
        $gate = (string)$pin['_gate'];
        // FIX: Use concatenated string key instead of array
        $pad = $pads[$gate . '|' . $name] ?? null;
        if ($pad) {
            $mx = $x + $dx*$ln/2; $my = $y + $dy*$ln/2;
            [$ox, $oy] = $vert ? [-0.3, 0.0] : [0.0, 0.3];
            [$tx, $ty] = $tf->pt($mx + $ox, $my + $oy);
            $cv->text(95, $tx, $ty, 1.27,
                      $tf->rot + ($tf->m ? (180 - $ang_local) : $ang_local),
                      $pad, "bottom-center", $tf->m);
        }
    }
}

function draw_symbol(&$cv, $sym, $tf, $libs_pad, $inst_name, $value, $smashed, $gate_label, $extra = null) {
    $subst = ['NAME' => $gate_label, 'VALUE' => $value];
    if ($extra) $subst = array_merge($subst, $extra);
    $ml = function ($n) { return $n; };
    foreach ($sym->children() as $ch) {
        if ($ch->getName() === 'pin') {
            draw_pin($cv, $ch, $tf, $libs_pad);
        } else {
            draw_common($cv, $ch, $tf, $ml, $subst, $smashed);
        }
    }
}

function render_sch($root) {
    $drawing = $root->drawing;
    $layers = parse_layers($drawing);
    $schematic = $drawing->schematic;
    $libs = parse_libs($schematic->libraries ?? null);
    $parts = [];
    foreach ($schematic->parts->part ?? [] as $p) $parts[(string)$p['name']] = $p;
    $sheets_el = $schematic->sheets->sheet ?? null;
$sheets = $sheets_el ? iterator_to_array($sheets_el) : [];
    $out = [];
    $sheet_counter = 0;
    foreach ($sheets as $idx => $sh) {
        $sheet_counter++;
        $cv = new Canvas($layers);
        $cv->no_mirror_text = true;
        $ident = new Tf();
        $plain = $sh->plain ?? null;
        if ($plain) {
            foreach ($plain->children() as $ch) {
                draw_common($cv, $ch, $ident, function ($n) { return $n; });
            }
        }
        $netmap = [];
        $nets_el = $sh->nets ?? null;
        if ($nets_el) {
            foreach ($nets_el->net as $net) {
                foreach ($net->pinref ?? [] as $pr) {
                    // FIX: Use concatenated string key instead of array
                    $key = (string)$pr['part'] . '|' . (string)$pr['gate'] . '|' . (string)$pr['pin'];
                    $netmap[$key] = (string)$net['name'];
                }
            }
        }
        $insts = $sh->instances ?? null;
        if ($insts) {
            foreach ($insts->instance as $inst) {
                $part_name = (string)$inst['part'];
                $part = $parts[$part_name] ?? null;
                if (!$part) continue;
                $lib = find_lib($libs, $part);
                $ix = num($inst, 'x'); $iy = num($inst, 'y');
                if (!$lib) {
                    warn("$part_name: library '" . (string)$part['library'] . "' not present");
                    missing_marker($cv, $ix, $iy, $part_name);
                    continue;
                }
                $dset = (string)$part['deviceset'];
                $gates = $lib['gates'][$dset] ?? null;
                $gate_name = (string)$inst['gate'];
                $why = null;
                if ($gates === null) $why = "library has no deviceset '$dset'";
                elseif (!isset($gates[$gate_name])) $why = "deviceset '$dset' has no gate '$gate_name'";
                elseif (!isset($lib['symbols'][$gates[$gate_name]])) $why = "symbol missing";
                if ($why) {
                    warn("$part_name: $why");
                    missing_marker($cv, $ix, $iy, $part_name);
                    continue;
                }
                $sym = $lib['symbols'][$gates[$gate_name]];
                $pads = [];
                $device = (string)($part['device'] ?? '');
                // FIX: Use concatenated string key
                $devmap = $lib['devmap'][$dset . '|' . $device] ?? [];
                foreach ($devmap as $k => $v) $pads[$k] = $v;
                
                // FIX: Check if attribute exists before adding
                foreach ($sym->pin ?? [] as $pin) {
                    if (!isset($pin['_gate'])) {
                        $pin->addAttribute('_gate', $gate_name);
                    }
                }
                
                [$m, $_sp, $a] = parse_rot($inst['rot'] ?? null);
                $tf = new Tf(num($inst, 'x'), num($inst, 'y'), $a, $m);
                $levels = $lib['addlevel'][$dset] ?? [];
                $level = $levels[$gate_name] ?? 'next';
                $same_kind = 0;
                foreach ($levels as $v) if (in_array($v, ['next', 'can'])) $same_kind++;
                $add = in_array($level, ['always', 'must', 'request']) || $same_kind > 1;
                $label = $part_name . ($add ? $gate_name : '');
                $smashed = ((string)$inst['smashed']) === 'yes';
                $value = (string)($part['value'] ?? '');
                if ($value === '') {
                    $sup = [];
                    foreach ($sym->pin ?? [] as $pin) {
                        if ((string)$pin['direction'] === 'sup') $sup[] = $pin;
                    }
                    if ($sup) {
                        // FIX: Use concatenated string key
                        $sup_key = $part_name . '|' . $gate_name . '|' . (string)$sup[0]['name'];
                        $value = $netmap[$sup_key] ?? (string)$sup[0]['name'];
                    } else {
                        $ds = (string)$part['deviceset'];
                        $dv = (string)($part['device'] ?? '');
                        $tech = (string)($part['technology'] ?? '');
                        $value = strpos($ds, '*') !== false ? str_replace('*', $tech, $ds) : $ds . $tech;
                        $value = strpos($value, '?') !== false ? str_replace('?', $dv, $value) : $value . $dv;
                    }
                }
                $extra = [
                    'PART'  => $part_name,
                    'GATE'  => $gate_name,
                    'SHEET' => $sheet_counter . '/' . count($sheets),
                ];
                // FIX: Use xpath instead of direct property access
                $part_attrs = $part->xpath('attribute') ?: [];
                foreach ($part_attrs as $pa) {
                    $an = strtoupper((string)$pa['name']);
                    if (!isset($extra[$an])) $extra[$an] = (string)$pa['value'];
                }
                draw_symbol($cv, $sym, $tf, $pads, $part_name, $value, $smashed, $label, $extra);
                if ($smashed) {
                    // FIX: Use xpath instead of direct property access
                    $inst_attrs = $inst->xpath('attribute') ?: [];
                    foreach ($inst_attrs as $at) {
                        if (!isset($at['x']) || (string)$at['display'] === 'off') continue;
                        $an = strtoupper((string)$at['name']);
                        $txt = $an === 'NAME' ? $label : ($an === 'VALUE' ? $value : (string)$at['value']);
                        [$tm, $ts, $r] = parse_rot($at['rot'] ?? null);
                        $cv->text((int)($at['layer'] ?? 95), num($at, 'x'), num($at, 'y'),
                                  num($at, 'size', 1.778), $r, $txt,
                                  (string)($at['align'] ?? 'bottom-left'), $tm, $ts);
                    }
                }
            }
        }
        foreach ([['net', 'nets'], ['bus', 'busses']] as $tag_grp) {
            $g = $sh->{$tag_grp[1]} ?? null;
            if (!$g) continue;
            foreach ($g->{$tag_grp[0]} as $net) {
                foreach ($net->segment ?? [] as $seg) {
                    foreach ($seg->children() as $ch) {
                        $tag = $ch->getName();
                        if ($tag === 'wire') {
                            draw_common($cv, $ch, $ident, function ($n) { return $n; });
                        } elseif ($tag === 'junction') {
                            $cv->circle(91, [num($ch, 'x'), num($ch, 'y')], 0.508, 0, true);
                        } elseif ($tag === 'label') {
                            [$m, $sp, $a] = parse_rot($ch['rot'] ?? null);
                            $name = (string)$net['name'];
                            if ($tag_grp[0] === 'bus') $name = explode(':', $name)[0];
                            if ((string)$ch['xref'] === 'yes' && $tag_grp[0] === 'net') {
                                draw_xref_flag($cv, (int)($ch['layer'] ?? 95),
                                               num($ch, 'x'), num($ch, 'y'),
                                               num($ch, 'size', 1.778),
                                               (string)$ch['rot'], $name);
                            } else {
                                $cv->text((int)($ch['layer'] ?? 95), num($ch, 'x'), num($ch, 'y'),
                                          num($ch, 'size', 1.778), $a, $name,
                                          "bottom-left", $m, $sp);
                            }
                        }
                    }
                }
            }
        }
        $suffix = count($sheets) === 1 ? "" : "_sheet" . $sheet_counter;
        $out[] = [$suffix, $cv, $GLOBALS['SCH_ORDER']];
    }
    return $out;
}

// ----------------------------------------------------------------- output
function pattern_def($pid, $color, $kind, $sp, $px = 6) {
    $rot = ["/" => -45, "\\" => 45, "-" => 0, "|" => 90, "x" => 45][$kind];
    $h = $sp / 2;
    $lines = sprintf("M0,%.3f L%.3f,%.3f", $h, $sp, $h);
    if ($kind === 'x') $lines .= sprintf(" M%.3f,0 L%.3f,%.3f", $h, $h, $sp);
    return sprintf(
        '<pattern id="%s" patternUnits="userSpaceOnUse" width="%.3f" height="%.3f" ' .
        'patternTransform="rotate(%d)" data-kind="%s" data-px="%d">' .
        '<path d="%s" stroke="%s" stroke-width="0.12" fill="none"/></pattern>',
        $pid, $sp, $sp, $rot, $kind, $px, $lines, $color);
}

function apply_fill($item, $fill, $pid, $min_w = 0.0) {
    if (!(strpos($item, '<path') === 0 || strpos($item, '<circle') === 0)) return $item;
    $target = $fill === 0 ? "none" : "url(#$pid)";
    $item = str_replace('fill="currentColor"', 'fill="' . $target . '"', $item);
    if ($fill === 0 || strpos($item, 'stroke="currentColor"') === false) return $item;
    if (preg_match('/stroke-width="([\d.]+)"/', $item, $m)) {
        if ($min_w > 0) {
            $item = preg_replace('/stroke-width="[\d.]+"/',
                sprintf('stroke-width="%.4f"', max((float)$m[1], $min_w)), $item, 1);
            $item = str_replace('stroke="currentColor"', 'stroke="' . $target . '"', $item);
        } elseif (strpos($item, 'stroke-linecap') !== false && (float)$m[1] >= 0.4) {
            $item = str_replace('stroke="currentColor"', 'stroke="' . $target . '"', $item);
        }
    }
    return $item;
}

function layer_color($layers, $n) {
    global $PALETTE;
    $info = $layers[$n] ?? null;
    if (!$info) return "#c8c8c8";
    return $PALETTE[$info['color']] ?? "#c8c8c8";
}

function build_svg(&$cv, $order) {
    global $FILL_PATTERNS, $FILL_PX, $KEEPOUT_RESTRICT, $KEEPOUT_RESTRICT_WIDTH;
    [$x0, $y0, $x1, $y1] = $cv->bbox;
    $mg = max($x1 - $x0, $y1 - $y0) * 0.03 + 1.0;
    $vb = [$x0 - $mg, -$y1 - $mg, ($x1 - $x0) + 2*$mg, ($y1 - $y0) + 2*$mg];
    $used = [];
    foreach ($order as $n) if (isset($cv->items[$n])) $used[] = $n;
    $extra = array_keys($cv->items);
    sort($extra);
    foreach ($extra as $n) if (!in_array($n, $used)) $used[] = $n;
    $groups = []; $info = []; $defs = [];
    foreach ($used as $n) {
        $meta = $cv->layers[$n] ?? ['name' => (string)$n, 'visible' => true];
        $col = layer_color($cv->layers, $n);
        $vis = $meta['visible'];
        $items = $cv->items[$n];
        $fill = $meta['fill'] ?? 1;
        if ($fill === 0 || isset($FILL_PATTERNS[$fill])) {
            $pid = "hatch$n";
            $mw = in_array($n, $KEEPOUT_RESTRICT) ? $KEEPOUT_RESTRICT_WIDTH : 0.0;
            if (isset($FILL_PATTERNS[$fill])) {
                [$kind, $sp] = $FILL_PATTERNS[$fill];
                if ($mw > 0) {
                    $defs[] = pattern_def($pid, $col, $kind, $mw, $FILL_PX[$fill] ?? 6);
                } else {
                    $defs[] = pattern_def($pid, $col, $kind, $sp, $FILL_PX[$fill] ?? 6);
                }
            }
            $mapped = [];
            foreach ($items as $it) $mapped[] = apply_fill($it, $fill, $pid, $mw);
            $items = $mapped;
        }
        $style = $vis ? '' : ' style="display:none"';
        $groups[] = sprintf('<g id="L%d" color="%s"%s>%s</g>',
                            $n, $col, $style, "\n" . implode("\n", $items) . "\n");
        $info[] = ["L$n", "$n " . $meta['name'], $col, $vis];
    }
    $svg = sprintf(
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="%.3f %.3f %.3f %.3f">' .
        '<defs>%s</defs><rect x="%.3f" y="%.3f" width="%.3f" height="%.3f" fill="#000"/>' .
        '<g id="content">%s</g></svg>',
        $vb[0], $vb[1], $vb[2], $vb[3],
        implode('', $defs),
        $vb[0], $vb[1], $vb[2], $vb[3],
        "\n" . implode("\n", $groups) . "\n");
    return [$svg, $info, implode('', $defs)];
}

// ----------------------------------------------------------------- 3D helpers
function arc_points($p1, $p2, $curve, $step = 6.0) {
    $chord = sqrt(($p1[0]-$p2[0])**2 + ($p1[1]-$p2[1])**2);
    if (abs($curve) <= 0.01 || $chord < 1e-9) return [$p2];
    $th = deg2rad($curve);
    $r = $chord / (2 * sin(abs($th) / 2));
    $mx = ($p1[0]+$p2[0])/2; $my = ($p1[1]+$p2[1])/2;
    $lx = -($p2[1]-$p1[1])/$chord; $ly = ($p2[0]-$p1[0])/$chord;
    $d = $r * cos(abs($th)/2) * ($th > 0 ? 1 : -1);
    $cx = $mx + $lx*$d; $cy = $my + $ly*$d;
    $a0 = atan2($p1[1]-$cy, $p1[0]-$cx);
    $n = max(2, (int)(abs($curve)/$step) + 1);
    $pts = [];
    for ($i = 1; $i < $n; $i++) {
        $pts[] = [$cx + $r*cos($a0 + $th*$i/$n), $cy + $r*sin($a0 + $th*$i/$n)];
    }
    $pts[] = $p2;
    return $pts;
}

function poly_area($pts) {
    $sum = 0; $n = count($pts);
    for ($i = 0; $i < $n; $i++) {
        $j = ($i + 1) % $n;
        $sum += $pts[$i][0]*$pts[$j][1] - $pts[$j][0]*$pts[$i][1];
    }
    return 0.5 * $sum;
}

function point_in_poly($pt, $poly) {
    [$x, $y] = $pt; $inside = false; $n = count($poly);
    for ($i = 0; $i < $n; $i++) {
        $j = ($i + 1) % $n;
        $x1 = $poly[$i][0]; $y1 = $poly[$i][1];
        $x2 = $poly[$j][0]; $y2 = $poly[$j][1];
        if (($y1 > $y) !== ($y2 > $y) &&
            $x < ($x2 - $x1) * ($y - $y1) / ($y2 - $y1) + $x1) {
            $inside = !$inside;
        }
    }
    return $inside;
}

// Outline diagnostics of the last build_outline() call (used for a meaningful message when it fails)
$OUTLINE_DIAG = ['tol' => null, 'ends' => [], 'segs' => 0];

function strip_spikes($ids) {
    // remove zero-width spikes (a, b, a): bridges traversed twice by the face walk
    $changed = true;
    while ($changed && count($ids) >= 3) {
        $changed = false;
        $n = count($ids);
        for ($i = 0; $i < $n; $i++) {
            if ($ids[$i] === $ids[($i + 2) % $n]) {
                $rm = [($i + 1) % $n, ($i + 2) % $n];
                rsort($rm);
                foreach ($rm as $k) array_splice($ids, $k, 1);
                $changed = true;
                break;
            }
        }
    }
    return $ids;
}

// Closed outer boundaries of every connected group of layer-20 segments.
// Works on a planar graph: end points are snapped together ($tol), segments are split where they touch or
// cross (T junctions, overlaps between the board outline and an outline drawn inside a component package),
// dangling pieces are pruned, then the outer boundary of every connected component is walked.
function outline_loops($segs, $tol, &$ends) {
    $V = []; $grid = [];
    $vid = function ($p) use (&$V, &$grid, $tol) {
        $ix = (int)floor($p[0] / $tol); $iy = (int)floor($p[1] / $tol);
        for ($dx = -1; $dx <= 1; $dx++) for ($dy = -1; $dy <= 1; $dy++) {
            $k = ($ix + $dx) . ',' . ($iy + $dy);
            if (isset($grid[$k])) foreach ($grid[$k] as $id) {
                if (hypot($V[$id][0] - $p[0], $V[$id][1] - $p[1]) <= $tol) return $id;
            }
        }
        $id = count($V); $V[] = $p; $grid[$ix . ',' . $iy][] = $id;
        return $id;
    };
    $E = [];
    foreach ($segs as $sg) {
        [$a, $b, $c] = $sg;
        $pts = array_merge([$a], arc_points($a, $b, $c));
        for ($i = 0; $i < count($pts) - 1; $i++) {
            $u = $vid($pts[$i]); $w = $vid($pts[$i + 1]);
            if ($u !== $w) $E[] = [$u, $w];
        }
    }
    $n = count($E); $nv = count($V);
    $splits = array_fill(0, $n, []);
    if ($n * $nv <= 8000000) {                    // vertices lying on the inside of another edge (T junctions)
        for ($e = 0; $e < $n; $e++) {
            [$u, $w] = $E[$e]; $p = $V[$u]; $q = $V[$w];
            $dx = $q[0] - $p[0]; $dy = $q[1] - $p[1]; $len2 = $dx * $dx + $dy * $dy;
            if ($len2 < 1e-18) continue;
            for ($k = 0; $k < $nv; $k++) {
                if ($k === $u || $k === $w) continue;
                $t = (($V[$k][0] - $p[0]) * $dx + ($V[$k][1] - $p[1]) * $dy) / $len2;
                if ($t <= 0 || $t >= 1) continue;
                if (hypot($V[$k][0] - ($p[0] + $t * $dx), $V[$k][1] - ($p[1] + $t * $dy)) <= $tol) $splits[$e][] = [$t, $k];
            }
        }
    }
    if ($n <= 3000) {                             // proper crossings between two edges
        for ($e = 0; $e < $n; $e++) {
            for ($f = $e + 1; $f < $n; $f++) {
                if ($E[$e][0] === $E[$f][0] || $E[$e][0] === $E[$f][1] || $E[$e][1] === $E[$f][0] || $E[$e][1] === $E[$f][1]) continue;
                $p = $V[$E[$e][0]]; $q = $V[$E[$e][1]]; $r = $V[$E[$f][0]]; $s2 = $V[$E[$f][1]];
                $d = ($q[0] - $p[0]) * ($s2[1] - $r[1]) - ($q[1] - $p[1]) * ($s2[0] - $r[0]);
                if (abs($d) < 1e-12) continue;
                $t = (($r[0] - $p[0]) * ($s2[1] - $r[1]) - ($r[1] - $p[1]) * ($s2[0] - $r[0])) / $d;
                $u2 = (($r[0] - $p[0]) * ($q[1] - $p[1]) - ($r[1] - $p[1]) * ($q[0] - $p[0])) / $d;
                if ($t > 0 && $t < 1 && $u2 > 0 && $u2 < 1) {
                    $id = $vid([$p[0] + $t * ($q[0] - $p[0]), $p[1] + $t * ($q[1] - $p[1])]);
                    $splits[$e][] = [$t, $id]; $splits[$f][] = [$u2, $id];
                }
            }
        }
    }
    $nb = [];                                      // unique undirected edges
    $addEdge = function ($a, $b) use (&$nb) {
        if ($a === $b) return;
        $nb[$a][$b] = true; $nb[$b][$a] = true;
    };
    for ($e = 0; $e < $n; $e++) {
        $sp = $splits[$e];
        usort($sp, function ($x, $y) { return $x[0] <=> $y[0]; });
        $chain = [$E[$e][0]];
        foreach ($sp as $x) $chain[] = $x[1];
        $chain[] = $E[$e][1];
        for ($i = 0; $i < count($chain) - 1; $i++) $addEdge($chain[$i], $chain[$i + 1]);
    }
    // prune dangling pieces; their free ends are reported when nothing closes
    $ends = [];
    $queue = [];
    foreach ($nb as $v => $ns) {
        if (count($ns) === 1) { $ends[] = $V[$v]; $queue[] = $v; }
    }
    while ($queue) {
        $v = array_pop($queue);
        if (!isset($nb[$v])) continue;
        foreach (array_keys($nb[$v]) as $w) {
            unset($nb[$w][$v]);
            if (count($nb[$w]) <= 1) $queue[] = $w;
        }
        unset($nb[$v]);
    }
    foreach ($nb as $v => $ns) { if (!$ns) unset($nb[$v]); }
    $order = []; $pos = [];
    foreach ($nb as $v => $ns) {
        $keys = array_keys($ns);
        usort($keys, function ($a, $b) use ($V, $v) {
            return atan2($V[$a][1] - $V[$v][1], $V[$a][0] - $V[$v][0]) <=> atan2($V[$b][1] - $V[$v][1], $V[$b][0] - $V[$v][0]);
        });
        $order[$v] = $keys;
        foreach ($keys as $i => $k) $pos[$v][$k] = $i;
    }
    $seen = []; $loops = [];
    foreach ($nb as $u0 => $ns0) {
        foreach (array_keys($ns0) as $v0) {
            if (isset($seen[$u0 . '>' . $v0])) continue;
            $cyc = []; $a = $u0; $b = $v0; $guard = 0;
            do {
                $seen[$a . '>' . $b] = true;
                $cyc[] = $a;
                $ord = $order[$b];
                $nxt = $ord[($pos[$b][$a] - 1 + count($ord)) % count($ord)];
                $a = $b; $b = $nxt;
            } while (!($a === $u0 && $b === $v0) && ++$guard < 200000);
            $cyc = strip_spikes($cyc);
            if (count($cyc) < 3) continue;
            $pts = array_map(function ($id) use ($V) { return $V[$id]; }, $cyc);
            $ar = poly_area($pts);
            if ($ar < -1e-9) $loops[] = array_reverse($pts);   // clockwise walk = outer boundary of a component
        }
    }
    return $loops;
}

function build_outline($segs, $circles, $tol = 0.05) {
    global $OUTLINE_DIAG;
    $OUTLINE_DIAG = ['tol' => null, 'ends' => [], 'segs' => count($segs)];
    $loops = [];
    foreach ($circles as $cr) {
        [$c, $r] = $cr;
        $loop = [];
        for ($i = 0; $i < 48; $i++) {
            $loop[] = [$c[0] + $r*cos(2*M_PI*$i/48), $c[1] + $r*sin(2*M_PI*$i/48)];
        }
        $loops[] = $loop;
    }
    if ($segs) {
        $found = [];
        foreach ([$tol, 0.2, 0.5] as $t) {       // progressively looser snapping when end points do not meet exactly
            $ends = [];
            $found = outline_loops($segs, $t, $ends);
            if ($t === $tol) $OUTLINE_DIAG['ends'] = $ends;
            if ($found) { $OUTLINE_DIAG['tol'] = $t; break; }
        }
        if (!$found) return [null, []];            // wires exist but do not close: do not guess
        $loops = array_merge($loops, $found);
    }
    if (!$loops) return [null, []];
    usort($loops, function ($a, $b) { return abs(poly_area($b)) <=> abs(poly_area($a)); });
    $outer = $loops[0];
    $holes = [];
    for ($i = 1; $i < count($loops); $i++) {
        if (point_in_poly($loops[$i][0], $outer)) $holes[] = $loops[$i];
    }
    return [$outer, $holes];
}

// ----------------------------------------------------------------- HTML templates
$HTML_TMPL = <<<'HTML'
<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>__TITLE__</title>
<style>
body{margin:0;display:flex;height:100vh;background:#000;color:#ddd;font:13px sans-serif}
#side{width:230px;overflow:auto;padding:8px;background:#161616;border-right:1px solid #333}
#side label{display:block;white-space:nowrap;cursor:pointer;padding:1px 0}
#side button{margin:0 4px 8px 0}
#nav{margin:6px 0 10px}
#nav a,#nav .cur{display:inline-block;padding:3px 8px;margin:0 4px 4px 0;border-radius:3px;font-size:12px}
#nav a{background:#32324a;color:#6ee6e6;text-decoration:none}
#nav a:hover{background:#44445f}
#nav .cur{background:#222;color:#888}
#view{flex:1;min-width:0;position:relative}
#view>svg{width:100%;height:100%;display:block;touch-action:none;cursor:grab}
#v3d{position:absolute;inset:0;display:none;background:#101010}
#v3d canvas{display:block}
#bar3d{position:absolute;top:8px;left:8px;z-index:2}
#bar3d button{margin-right:4px}
#bar3d label{margin-left:8px}
#msg3d{position:absolute;bottom:8px;left:8px;z-index:2;color:#999}
</style></head><body>
<div id="side"><b>__TITLE__</b><br>__NAV__<br>
<button id="fit">Fit</button><button id="all">All</button><button id="none">None</button>__FLIP____BTN3D__
__LAYERS__</div>
<div id="view">__SVG__
__OVERLAY3D__</div>
<script>
const svg = document.querySelector('#view > svg');
const vb0 = svg.getAttribute('viewBox').split(' ').map(Number);
let vb = vb0.slice();
const pats = [...document.querySelectorAll('pattern[data-px]')];
function scalePatterns() {
    const s = svg.getScreenCTM().a;
    if (!s) return;
    pats.forEach(p => {
        const t = (+p.dataset.px) / s, h = t / 2, path = p.firstElementChild;
        p.setAttribute('width', t); p.setAttribute('height', t);
        path.setAttribute('d', 'M0,' + h + ' L' + t + ',' + h + (p.dataset.kind === 'x' ? ' M' + h + ',0 L' + h + ',' + t : ''));
        path.setAttribute('stroke-width', 1.1 / s);
    });
}
const apply = () => { svg.setAttribute('viewBox', vb.join(' ')); scalePatterns(); };
window.addEventListener('resize', scalePatterns);
setTimeout(scalePatterns, 0);
document.getElementById('fit').onclick = () => { vb = vb0.slice(); apply(); };
const flipBtn = document.getElementById('flip');
if (flipBtn) {
    let flipped = false;
    flipBtn.onclick = () => {
        flipped = !flipped;
        document.getElementById('content').setAttribute('transform',
            flipped ? 'translate(' + (2 * vb0[0] + vb0[2]) + ',0) scale(-1,1)' : '');
    };
}
const boxes = [...document.querySelectorAll('#side input')];
boxes.forEach(b => b.onchange = () => {
    document.getElementById(b.dataset.l).style.display = b.checked ? '' : 'none';
    if (window.layersChanged) window.layersChanged();
});
document.getElementById('all').onclick = () => boxes.forEach(b => { b.checked = true; b.onchange(); });
document.getElementById('none').onclick = () => boxes.forEach(b => { b.checked = false; b.onchange(); });
const toSvg = (cx, cy) => {
    const p = svg.createSVGPoint(); p.x = cx; p.y = cy;
    return p.matrixTransform(svg.getScreenCTM().inverse());
};
svg.addEventListener('wheel', e => {
    e.preventDefault();
    const k = e.deltaY > 0 ? 1.15 : 1 / 1.15;
    const p = toSvg(e.clientX, e.clientY);
    vb = [p.x - (p.x - vb[0]) * k, p.y - (p.y - vb[1]) * k, vb[2] * k, vb[3] * k];
    apply();
}, {passive: false});
let drag = null;
svg.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY]; svg.setPointerCapture(e.pointerId); });
svg.addEventListener('pointerup', () => drag = null);
svg.addEventListener('pointermove', e => {
    if (!drag) return;
    const s = svg.getScreenCTM().a;
    vb[0] -= (e.clientX - drag[0]) / s; vb[1] -= (e.clientY - drag[1]) / s;
    drag = [e.clientX, e.clientY]; apply();
});
</script>
__SCRIPTS3D__</body></html>
HTML;

$OVERLAY_3D = '<div id="v3d"><div id="bar3d"><button data-v="iso">Iso</button><button data-v="top">Top</button>' .
              '<button data-v="bottom">Bottom</button>' .
              '<label>Mask <select id="s-mask"></select></label>' .
              '<label>Finish <select id="s-fin"></select></label>' .
              '<label>Pads <select id="s-pad"></select></label></div><div id="msg3d"></div></div>';

function build_html($title, $svg, $info, $flip = false, $three = null) {
    global $HTML_TMPL, $OVERLAY_3D, $JS3D;
    $rows = [];
    foreach ($info as [$i, $lab, $col, $vis]) {
        $chk = $vis ? ' checked' : '';
        $rows[] = sprintf(
            '<label><input type="checkbox" data-l="%s"%s><span style="color:%s">&#9632;</span> %s</label>',
            $i, $chk, $col, htmlspecialchars($lab, ENT_QUOTES));
    }
    $page = strtr($HTML_TMPL, [
        '__TITLE__'    => htmlspecialchars($title, ENT_QUOTES),
        '__FLIP__'     => $flip ? '<button id="flip">Flip</button>' : '',
        '__BTN3D__'    => $three ? '<button id="b3d">3D rendering</button>' : '',
        '__LAYERS__'   => implode("\n", $rows),
        '__SVG__'      => $svg,
        '__OVERLAY3D__'=> $three ? $OVERLAY_3D : '',
        '__NAV__'      => '<!--NAV-->',
    ]);
    $scripts = "";
    if ($three) {
        [$data] = $three;
        $scripts = '<script type="application/json" id="data3d">' . $data . "</script>\n" .
                   '<script src="' . js_prefix() . 'three.min.js"></script>' . "\n" .
                   '<script src="' . js_prefix() . 'TrackballControls.js"></script>' . "\n" .
                   '<script>' . $JS3D . '</script>' . "\n";
    }
    return str_replace('__SCRIPTS3D__', $scripts, $page);
}

// ----------------------------------------------------------------- 3D JS
$JS3D = <<<'JS'
(function () {
const D = JSON.parse(document.getElementById('data3d').textContent);
const btn = document.getElementById('b3d'), host = document.getElementById('v3d');
const msg = document.getElementById('msg3d'), svg2d = document.querySelector('#view > svg');
const HINT = 'Left drag: rotate | wheel: zoom | right drag: pan | the 3D view follows the layer checkboxes';
const W = D.bbox[2], H = D.bbox[3], T = D.thickness;
const cx = D.bbox[0] + W / 2, cy = D.bbox[1] + H / 2;
const V = p => new THREE.Vector2(p[0] - cx, p[1] - cy);
const TOP = new Set(D.top_layers), BOT = new Set(D.bottom_layers);
const MASKS = {
    green: ['Green', '#0d6b36', '#2f9e58', '#f2f2f2'], red: ['Red', '#a31616', '#cf3b3b', '#f2f2f2'],
    blue: ['Blue', '#14409e', '#3c6bd0', '#f2f2f2'], yellow: ['Yellow', '#d4ae0a', '#ecd04a', '#151515'],
    white: ['White', '#dcdcdc', '#f6f6f6', '#151515'], black: ['Black', '#141414', '#2c2c2c', '#f2f2f2'],
    magenta: ['Magenta / Purple', '#8a1a7e', '#b24aa6', '#f2f2f2'], orange: ['Orange', '#d4621a', '#ee8a42', '#f2f2f2'],
    pink: ['Pink', '#d8648f', '#ef8fb2', '#f2f2f2'], gray: ['Gray', '#6f7377', '#8f9498', '#f2f2f2'],
    clear: ['Transparent (clear)', '#c2a066', '#b8733a', '#f2f2f2']};
const FINISHES = {glossy: ['Glossy', 45, 0x3a3a3a], matte: ['Matte', 4, 0x101010]};
const PADS = {gold: ['Gold (ENIG)', '#d9bf63'], tin: ['Tin (HASL)', '#c9ccd0'], copper: ['Bare copper', '#c87f4a']};
const selMask = document.getElementById('s-mask'), selFin = document.getElementById('s-fin'),
      selPad = document.getElementById('s-pad');
[[selMask, MASKS], [selFin, FINISHES], [selPad, PADS]].forEach(([sel, tab]) => {
    Object.keys(tab).forEach(k => sel.add(new Option(tab[k][0], k)));
    sel.onchange = () => window.layersChanged();
});
function palette() {
    const m = MASKS[selMask.value], p = PADS[selPad.value][1], s = m[3];
    return {base: m[1], pad: p, real: {1: m[2], 16: m[2], 17: p, 18: p,
            21: s, 22: s, 25: s, 26: s, 27: s, 28: s}};
}
const ser = new XMLSerializer();
let renderer, scene, camera, controls, group = null, dist = 1;
let active = false, ready = false, looping = false, timer = null, token = 0;
const on = n => { const b = document.querySelector('#side input[data-l="L' + n + '"]'); return !!b && b.checked; };
function pip(x, y, poly) {
    let inside = false;
    for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
        const xi = poly[i][0], yi = poly[i][1], xj = poly[j][0], yj = poly[j][1];
        if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
}
function textureSvg(top, pal) {
    const other = top ? BOT : TOP, cu = top ? 1 : 16;
    let body = '';
    document.querySelectorAll('#content > g').forEach(g => {
        const n = +g.id.slice(1);
        if (!on(n) || other.has(n) || (n >= 2 && n <= 15)) return;
        const c = g.cloneNode(true);
        c.querySelectorAll('.hr').forEach(e => e.remove());
        c.removeAttribute('style'); c.removeAttribute('id');
        c.setAttribute('color', pal.real[n] || g.getAttribute('color'));
        body += ser.serializeToString(c);
        if (n === cu && D.smd[cu]) body += '<g color="' + pal.pad + '">' + D.smd[cu] + '</g>';
    });
    const y0 = -(D.bbox[1] + H);
    return '<svg xmlns="http://www.w3.org/2000/svg" width="' + D.px[0] + '" height="' + D.px[1] +
           '" viewBox="' + D.bbox[0] + ' ' + y0 + ' ' + W + ' ' + H + '"><defs>' + D.defs + '</defs>' +
           '<rect x="' + D.bbox[0] + '" y="' + y0 + '" width="' + W + '" height="' + H + '" fill="' + pal.base + '"/>' +
           body + '</svg>';
}
function buildShape() {
    const shape = new THREE.Shape(D.outer.map(V));
    D.holes.forEach(h => shape.holes.push(new THREE.Path(h.map(V))));
    const seen = new Set();
    D.drills.forEach(d => {
        if (!on(d[3]) || d[2] <= 0) return;
        const k = d[0].toFixed(3) + ',' + d[1].toFixed(3) + ',' + d[2].toFixed(3);
        if (seen.has(k) || !pip(d[0], d[1], D.outer)) return;
        seen.add(k);
        const p = new THREE.Path();
        p.absarc(d[0] - cx, d[1] - cy, d[2], 0, Math.PI * 2, false);
        shape.holes.push(p);
    });
    return shape;
}
const img = s => new Promise((ok, ko) => {
    const url = URL.createObjectURL(new Blob([s], {type: 'image/svg+xml;charset=utf-8'}));
    const i = new Image();
    i.onload = () => { URL.revokeObjectURL(url); ok(i); };
    i.onerror = () => { URL.revokeObjectURL(url); ko(new Error('texture SVG could not be rasterized')); };
    i.src = url;
});
async function texture(s) {
    const a = await img(s);
    const c = document.createElement('canvas'); c.width = D.px[0]; c.height = D.px[1];
    c.getContext('2d').drawImage(a, 0, 0, c.width, c.height);
    const t = new THREE.CanvasTexture(c);
    t.encoding = THREE.sRGBEncoding; t.anisotropy = renderer.capabilities.getMaxAnisotropy();
    return t;
}
function face(shape, z, tex) {
    const fin = FINISHES[selFin.value];
    const g = new THREE.ShapeGeometry(shape, 16), p = g.attributes.position, u = g.attributes.uv;
    for (let i = 0; i < p.count; i++) u.setXY(i, (p.getX(i) + W / 2) / W, (p.getY(i) + H / 2) / H);
    g.translate(0, 0, z);
    return new THREE.Mesh(g, new THREE.MeshPhongMaterial({
        map: tex, side: THREE.DoubleSide, shininess: fin[1], specular: fin[2]}));
}
function disposeGroup(g) {
    g.traverse(o => {
        if (o.geometry) o.geometry.dispose();
        if (o.material) [].concat(o.material).forEach(m => { if (m.map) m.map.dispose(); m.dispose(); });
    });
}
async function rebuild() {
    const my = ++token;
    msg.textContent = 'Updating 3D view...';
    try {
        const shape = buildShape();
        const pal = palette();
        const [tt, tb] = await Promise.all([texture(textureSvg(true, pal)), texture(textureSvg(false, pal))]);
        if (my !== token) { tt.dispose(); tb.dispose(); return; }
        const g = new THREE.Group();
        const eg = new THREE.ExtrudeGeometry(shape, {depth: T, bevelEnabled: false, curveSegments: 16});
        eg.translate(0, 0, -T / 2);
        g.add(new THREE.Mesh(eg, [new THREE.MeshBasicMaterial({visible: false}),
                                  new THREE.MeshPhongMaterial({color: 0x9a8440, shininess: 10})]));
        g.add(face(shape, T / 2 + 0.02, tt));
        g.add(face(shape, -T / 2 - 0.02, tb));
        if (group) { scene.remove(group); disposeGroup(group); }
        group = g; scene.add(g);
        msg.textContent = HINT;
    } catch (e) { msg.textContent = '3D error: ' + e.message; }
}
function setView(x, y, z) {
    camera.position.set(x * dist, y * dist, z * dist);
    camera.up.set(0, 1, 0); controls.target.set(0, 0, 0); camera.lookAt(0, 0, 0); controls.update();
}
function resize() {
    if (!renderer) return;
    renderer.setSize(host.clientWidth, host.clientHeight);
    camera.aspect = host.clientWidth / host.clientHeight; camera.updateProjectionMatrix();
    controls.handleResize();
}
function init() {
    try { renderer = new THREE.WebGLRenderer({antialias: true}); }
    catch (e) { return false; }
    renderer.setPixelRatio(window.devicePixelRatio);
    renderer.outputEncoding = THREE.sRGBEncoding;
    host.insertBefore(renderer.domElement, host.firstChild);
    scene = new THREE.Scene();
    scene.background = new THREE.Color(0x101010);
    camera = new THREE.PerspectiveCamera(35, 1, 0.5, 20000);
    scene.add(new THREE.AmbientLight(0xffffff, 0.6));
    const l1 = new THREE.DirectionalLight(0xffffff, 0.7); l1.position.set(-1, -1, 2); scene.add(l1);
    const l2 = new THREE.DirectionalLight(0xffffff, 0.5); l2.position.set(1, 1, -2); scene.add(l2);
    dist = Math.max(W, H) * 1.8;
    controls = new THREE.TrackballControls(camera, renderer.domElement);
    controls.rotateSpeed = 3; controls.zoomSpeed = 1.2; controls.panSpeed = 0.8; controls.staticMoving = true;
    const views = {iso: [0, -0.55, 0.85], top: [0, 0, 1], bottom: [0, 0, -1]};
    host.querySelectorAll('#bar3d button').forEach(b => b.onclick = () => setView(...views[b.dataset.v]));
    window.addEventListener('resize', resize);
    host.style.display = 'block'; resize(); setView(...views.iso);
    ready = true;
    return true;
}
function loop() {
    if (!active) { looping = false; return; }
    looping = true; requestAnimationFrame(loop);
    controls.update(); renderer.render(scene, camera);
}
btn.onclick = () => {
    if (!active) {
        host.style.display = 'block';
        if (!ready && !init()) {
            host.style.display = 'none';
            btn.disabled = true; btn.textContent = '3D unavailable (no WebGL)';
            return;
        }
        active = true; svg2d.style.visibility = 'hidden'; btn.textContent = '2D view';
        resize(); rebuild(); if (!looping) loop();
    } else {
        active = false; host.style.display = 'none'; svg2d.style.visibility = ''; btn.textContent = '3D rendering';
    }
};
window.layersChanged = () => { if (active) { clearTimeout(timer); timer = setTimeout(rebuild, 300); } };
})();
JS;

// ----------------------------------------------------------------- 3D payload
function build_3d_payload(&$cv, $defs) {
    global $TOP_LAYERS, $BOTTOM_LAYERS, $BOARD_THICKNESS;
    [$outer, $holes] = build_outline($cv->outline_segs, $cv->outline_circles);
    if ($outer === null) {
        warn("3D view skipped - no closed board outline found on layer 20 (Dimension)");
        return null;
    }
    $xs = array_column($outer, 0); $ys = array_column($outer, 1);
    $bb = [min($xs), min($ys), max($xs) - min($xs), max($ys) - min($ys)];
    $ppm = min(20.0, 4096.0 / max($bb[2], $bb[3]));
    $rnd = function ($pts) {
        return array_map(function ($p) { return [round($p[0], 4), round($p[1], 4)]; }, $pts);
    };
    $data = [
        "outer"   => $rnd($outer),
        "holes"   => array_map($rnd, $holes),
        "bbox"    => $bb,
        "thickness" => $BOARD_THICKNESS,
        "px"      => [max(1, (int)($bb[2] * $ppm)), max(1, (int)($bb[3] * $ppm))],
        "drills"  => [],
        "smd"     => [
            "1"  => implode('', $cv->extra["smd|1"] ?? []),
            "16" => implode('', $cv->extra["smd|16"] ?? []),
        ],
        "defs"    => $defs,
        "top_layers"    => $TOP_LAYERS,
        "bottom_layers" => $BOTTOM_LAYERS,
    ];
    foreach ($cv->drills as $d) {
        [$c, $r, $layer] = $d;
        if ($r > 0) $data["drills"][] = [round($c[0], 4), round($c[1], 4), round($r, 4), $layer];
    }
    $json = json_encode($data, JSON_UNESCAPED_SLASHES);
    $json = str_replace('</', '<\\/', $json);
    return [$json];
}

// ----------------------------------------------------------------- detect type
function detect_type($xml) {
    $drawing = $xml->drawing ?? null;
    if (!$drawing) return null;

    $has_board = isset($drawing->board) && count($drawing->board->children()) > 0;
    $has_schematic = isset($drawing->schematic) && count($drawing->schematic->children()) > 0;

    if ($has_board) return 'board';
    if ($has_schematic) return 'schematic';
    return null;
}

// ----------------------------------------------------------------- process single file
function process_file($path, $outdir) {
    global $VARS, $BOARD_ORDER, $SCH_ORDER;
    $log = [];
    $written = [];

    libxml_use_internal_errors(true);
    $xml = @simplexml_load_file($path);

    if ($xml === false) {
        $log[] = "XML parse FAILED: " . basename($path);
        foreach (libxml_get_errors() as $err) {
            $log[] = "  XML error line " . $err->line . ": " . trim($err->message);
        }
        libxml_clear_errors();
        return [$written, $log];
    }

    $type = detect_type($xml);
    if ($type === null) {
        $log[] = "error: neither <board> nor <schematic> found in " . basename($path);
        return [$written, $log];
    }

    $info = pathinfo($path);
    $base = $info['filename'];
    $is_board = ($type === 'board');

    $VARS = [
        "DRAWING_NAME"   => basename($path),
        "LAST_DATE_TIME" => date('Y-m-d H:i:s', @filemtime($path) ?: time()),
        "PLOT_DATE_TIME" => date('Y-m-d H:i:s'),
    ];

    try {
        if ($is_board) {
            $log[] = "Detected: BOARD -> " . basename($path);
            $sheets = render_board($xml);
            $suffix_base = "_brd";
        } else {
            $log[] = "Detected: SCHEMATIC -> " . basename($path);
            $sheets = render_sch($xml);
            $suffix_base = "_sch";
        }

        foreach ($sheets as [$sheet_suffix, &$cv, $order]) {
            $name = $base . $suffix_base . $sheet_suffix;

            [$svg, $info_layers, $defs] = build_svg($cv, $order);
            $svg_path = $outdir . '/' . $name . '.svg';
            file_put_contents($svg_path, '<?xml version="1.0" encoding="UTF-8"?>' . "\n" . $svg);
            $log[] = "written: " . $name . ".svg";

            $three = null;
            if ($is_board) {
                $three = build_3d_payload($cv, $defs);
                if ($three === null) {
                    global $OUTLINE_DIAG;
                    $msg = "note: 3D view skipped - no closed outline on layer 20";
                    if ($OUTLINE_DIAG['segs'] > 0) {
                        $msg .= " (" . $OUTLINE_DIAG['segs'] . " segments found, parts inside component packages included";
                        $ends = array_slice($OUTLINE_DIAG['ends'], 0, 6);
                        if ($ends) {
                            $msg .= "; open ends near: " . implode(', ', array_map(function ($p) {
                                return '(' . round($p[0], 2) . ', ' . round($p[1], 2) . ') mm';
                            }, $ends));
                        }
                        $msg .= ")";
                    } else {
                        $msg .= " (no wire, rectangle or polygon on layer 20 found)";
                    }
                    $log[] = $msg;
                }
            }

            $hp = $outdir . '/' . $name . '.htm';
            file_put_contents($hp, build_html($name, $svg, $info_layers, $is_board, $three));

            if ($three !== null) {
                $log[] = "written: " . $name . ".htm (with 3D view)";
            } else {
                $log[] = "written: " . $name . ".htm";
            }
            $written[] = $hp;
        }

        return [$written, $log];
    } catch (Throwable $e) {
        $log[] = "EXCEPTION processing " . basename($path) . ": " . $e->getMessage();
        $log[] = "File: " . $e->getFile() . ":" . $e->getLine();
        return [$written, $log];
    }
}

// ----------------------------------------------------------------- input handling
const MAX_UPLOAD_FILES = 12;

// Where the viewers find three.min.js / TrackballControls.js (viewers live in output/<run>/)
function js_prefix() {
    if (is_file(__DIR__ . '/three.min.js')) return '../../';          // next to this script
    if (is_file(__DIR__ . '/output/three.min.js')) return '../';       // inside output/
    return '../../';
}

function upload_error_text($code) {
    switch ($code) {
        case UPLOAD_ERR_INI_SIZE:
        case UPLOAD_ERR_FORM_SIZE:
            return 'file too large (server limit upload_max_filesize = ' . ini_get('upload_max_filesize') . ')';
        case UPLOAD_ERR_PARTIAL:   return 'upload interrupted, please retry';
        case UPLOAD_ERR_NO_FILE:   return 'no file selected';
        case UPLOAD_ERR_NO_TMP_DIR:
        case UPLOAD_ERR_CANT_WRITE: return 'the server cannot store the file';
        default:                   return 'upload failed (code ' . $code . ')';
    }
}

// $_FILES['eagle_file'] holds one file or (with name="eagle_file[]") a list: always return a list
function normalize_uploads($f) {
    $out = [];
    foreach (['name', 'tmp_name', 'error'] as $c) $f[$c] = (array)($f[$c] ?? []);
    foreach ($f['name'] as $i => $name) {
        $out[] = ['name' => (string)$name, 'tmp' => $f['tmp_name'][$i] ?? '', 'error' => (int)($f['error'][$i] ?? UPLOAD_ERR_NO_FILE)];
    }
    return $out;
}

// One single working folder: output/run-<random>/ holds the generated viewers of one render. The uploaded
// sources are deleted as soon as they have been rendered, the whole run folder when the page is closed
// (browser beacon) or, as a safety net, after RUN_MAX_AGE seconds.
const RUN_MAX_AGE = 7200;

function run_id_ok($run) {
    return is_string($run) && preg_match('/^run-\d{8}-\d{6}-[a-f0-9]{32}$/', $run) === 1;
}

// Recursive delete of a folder (never follows symlinks)
function rrmdir($dir) {
    if (!is_dir($dir) || is_link($dir)) return;
    foreach (scandir($dir) ?: [] as $f) {
        if ($f === '.' || $f === '..') continue;
        $p = $dir . DIRECTORY_SEPARATOR . $f;
        if (is_dir($p) && !is_link($p)) rrmdir($p); else @unlink($p);
    }
    @rmdir($dir);
}

function purge_old_runs($root, $max_age = RUN_MAX_AGE) {
    foreach (glob($root . '/run-*', GLOB_ONLYDIR) ?: [] as $d) {
        if (time() - (int)@filemtime($d) >= $max_age) rrmdir($d);
    }
}

function viewer_label($file) {
    $b = basename($file, '.htm');
    if (preg_match('/_(brd|sch)(.*)$/', $b, $m)) {
        $k = ($m[1] === 'brd') ? 'Board' : 'Schematic';
        $rest = trim($m[2], '_');
        return $rest !== '' ? $k . ' (' . $rest . ')' : $k;
    }
    return $b;
}

// Fills the <!--NAV--> placeholder of every viewer with links to the other viewers of the same group
function inject_nav($written) {
    foreach ($written as $hp) {
        $nav = '';
        if (count($written) > 1) {
            $nav = '<div id="nav">';
            foreach ($written as $o) {
                $lab = htmlspecialchars(viewer_label($o), ENT_QUOTES);
                $nav .= ($o === $hp) ? '<span class="cur">' . $lab . '</span>'
                                     : '<a href="' . htmlspecialchars(basename($o), ENT_QUOTES) . '">' . $lab . '</a>';
            }
            $nav .= '</div><script>if(window.top!==window.self)document.getElementById("nav").style.display="none"</script>';
        }
        $html = file_get_contents($hp);
        $pos = strpos($html, '<!--NAV-->');
        if ($html !== false && $pos !== false) {
            file_put_contents($hp, substr_replace($html, $nav, $pos, strlen('<!--NAV-->')));
        }
    }
}

// ----------------------------------------------------------------- process a group (same base name)
// $paths: saved files sharing the same base name, e.g. test.brd + test.sch uploaded together
function process_group($paths, $outdir, $base) {
    $order = ['brd' => 0, 'sch' => 1, 'xml' => 2];
    usort($paths, function ($a, $b) use ($order) {
        return ($order[strtolower(pathinfo($a, PATHINFO_EXTENSION))] ?? 9) <=> ($order[strtolower(pathinfo($b, PATHINFO_EXTENSION))] ?? 9);
    });
    $written = [];
    $log = [];
    $exts = [];
    foreach ($paths as $p) {
        $exts[] = strtolower(pathinfo($p, PATHINFO_EXTENSION));
        [$w, $l] = process_file($p, $outdir);
        $written = array_merge($written, $w);
        $log = array_merge($log, $l);
    }
    inject_nav($written);
    return [$written, $log];
}

// ================================================================= MAIN
session_set_cookie_params(['httponly' => true, 'samesite' => 'Lax']);
session_start();
$root = __DIR__ . '/output';

// The page asks for the cleanup of its run folder when it is closed (only runs of this session are deletable)
if (($_POST['action'] ?? '') === 'cleanup') {
    $run = $_POST['run'] ?? '';
    if (run_id_ok($run) && in_array($run, $_SESSION['runs'] ?? [], true)) {
        rrmdir($root . '/' . $run);
        $_SESSION['runs'] = array_values(array_diff($_SESSION['runs'], [$run]));
    }
    http_response_code(204);
    exit;
}

$action = $_POST['action'] ?? '';
$messages = [];
$groups_out = [];   // [['base' => ..., 'items' => [['label' => ..., 'url' => ...], ...]], ...]
$run = '';

if ($action === 'render' && isset($_FILES['eagle_file'])) {
    $ups = normalize_uploads($_FILES['eagle_file']);
    $ups = array_values(array_filter($ups, function ($u) { return !($u['error'] === UPLOAD_ERR_NO_FILE && $u['name'] === ''); }));
    if (!$ups) {
        $messages[] = "error: no file selected";
    } elseif (count($ups) > MAX_UPLOAD_FILES) {
        $messages[] = "error: too many files (maximum " . MAX_UPLOAD_FILES . ")";
    } else {
        if (!is_dir($root)) @mkdir($root, 0777, true);
        if (!is_file($root . '/.htaccess')) @file_put_contents($root . '/.htaccess', "Options -Indexes\n");
        foreach ($_SESSION['runs'] ?? [] as $old) { if (run_id_ok($old)) rrmdir($root . '/' . $old); }   // previous render of this session
        purge_old_runs($root);
        $run = 'run-' . date('Ymd-His') . '-' . bin2hex(random_bytes(16));
        $outdir = $root . '/' . $run;
        if (!@mkdir($outdir, 0777, true)) {
            $messages[] = "error: cannot create the output folder";
            $run = '';
        } else {
            $_SESSION['runs'] = [$run];
            session_write_close();      // do not keep the session locked while rendering
            $groups = [];
            $batch_seen = [];
            foreach ($ups as $u) {
                if ($u['error'] !== UPLOAD_ERR_OK) {
                    $messages[] = "error: " . $u['name'] . " - " . upload_error_text($u['error']);
                    continue;
                }
                $ext = strtolower(pathinfo($u['name'], PATHINFO_EXTENSION));
                if (!in_array($ext, ['brd', 'sch', 'xml'], true)) {
                    $messages[] = "error: " . $u['name'] . " - only .brd, .sch or .xml files are accepted";
                    continue;
                }
                $base = preg_replace('/[^A-Za-z0-9._-]/', '_', pathinfo($u['name'], PATHINFO_FILENAME));
                if (isset($batch_seen[strtolower($base . '.' . $ext)])) {
                    $messages[] = "error: " . $u['name'] . " - duplicate file name ignored";
                    continue;
                }
                $batch_seen[strtolower($base . '.' . $ext)] = true;
                $dest = $outdir . '/' . $base . '.' . $ext;
                if (!move_uploaded_file($u['tmp'], $dest)) {
                    $messages[] = "error: " . $u['name'] . " - could not save the uploaded file";
                    continue;
                }
                $groups[strtolower($base)][] = $dest;
            }
            foreach ($groups as $key => $paths) {
                // Pre-render companion check: the upload has arrived, but rendering has not started yet.
                $group_exts = [];
                foreach ($paths as $pth) {
                    $group_exts[strtolower(pathinfo($pth, PATHINFO_EXTENSION))] = true;
                }
                if (isset($group_exts['brd']) xor isset($group_exts['sch'])) {
                    $missing = isset($group_exts['brd']) ? 'schematic (.sch)' : 'board (.brd)';
                    $messages[] = "note: companion missing for '$key' - no matching $missing was uploaded; rendering the available file only";
                }
                [$written, $log] = process_group($paths, $outdir, $key);
                $messages = array_merge($messages, $log);
                $items = [];
                foreach ($written as $hp) {
                    $items[] = ['label' => viewer_label($hp), 'url' => 'output/' . $run . '/' . basename($hp)];
                }
                if ($items) $groups_out[] = ['base' => $key, 'items' => $items];
                foreach ($paths as $pth) @unlink($pth);   // the sources are not needed any more: delete them now
            }
        }
    }
}
?>
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>EaglePCBView3D - Web</title>
<style>
body { font-family: sans-serif; background: #1a1a1a; color: #ddd; margin: 20px; }
h1 { color: #6ee66e; }
form { background: #252525; padding: 20px; border-radius: 6px; max-width: 700px; }
#drop { border: 2px dashed #555; border-radius: 6px; padding: 18px; text-align: center; color: #aaa; }
#drop.over { border-color: #6ee66e; color: #6ee66e; }
.row { margin: 12px 0; display: flex; gap: 8px; flex-wrap: wrap; }
#projects { margin: 10px 0; font-size: 14px; }
.proj { padding: 6px 8px; background: #2d2d2d; border-radius: 4px; margin-bottom: 4px; }
.proj label { cursor: pointer; }
.ok { color: #6ee66e; }
.no { color: #e6c46e; }
.proj button { padding: 2px 8px; font-size: 12px; margin-left: 8px; background: #444; }
button { background: #3c3cf0; color: white; border: none; padding: 10px 20px;
         border-radius: 4px; cursor: pointer; font-size: 14px; }
button:hover { background: #5555ff; }
button:disabled { background: #444; color: #888; cursor: default; }
.msg { padding: 4px 0; font-family: monospace; font-size: 13px; }
.msg.ok { color: #6ee66e; }
.msg.warn { color: #e6c46e; }
.msg.err { color: #ff7878; }
.group { background: #252525; border-radius: 6px; padding: 12px 16px; margin-top: 16px; }
.group b { color: #ddd; }
.tabs { margin: 8px 0; display: flex; gap: 6px; align-items: center; flex-wrap: wrap; }
.tab { background: #32324a; color: #6ee6e6; padding: 6px 14px; }
.tab:hover { background: #44445f; }
.tab.on { background: #3c3cf0; color: #fff; }
.tabs a { color: #999; font-size: 12px; margin-left: 10px; }
.tabs .fs { background: #444; padding: 6px 10px; font-size: 12px; }
.frames { background: #000; }
.frames iframe { width: 100%; height: 82vh; border: 1px solid #444; display: none; background: #000; }
.frames iframe.on { display: block; }
.frames:fullscreen iframe { height: 100vh; border: 0; }
.info { color: #888; font-size: 12px; margin-top: 14px; max-width: 700px; }

#companionModal[hidden] { display:none; }
#companionModal { position:fixed; inset:0; z-index:9999; display:flex; align-items:center; justify-content:center;
    padding:20px; background:rgba(0,0,0,.72); }
#companionDialog { width:min(520px,100%); box-sizing:border-box; padding:22px; border:1px solid #555;
    border-radius:8px; background:#252525; box-shadow:0 12px 40px #000; }
#companionDialog h2 { margin:0 0 12px; color:#e6c46e; font-size:19px; }
#companionDialog p { line-height:1.5; }
#companionDialog code { color:#6ee6e6; }
#companionDialog .actions { display:flex; gap:8px; justify-content:flex-end; flex-wrap:wrap; margin-top:20px; }
#companionDialog button.secondary { background:#444; }

</style>
</head>
<body>
<h1>EaglePCBView3D - Web</h1>
<form method="post" enctype="multipart/form-data" id="frm">
    <input type="hidden" name="action" value="render">
    <p>Select your EAGLE <b>.brd</b> and/or <b>.sch</b> files. Matching files with the same base name are paired automatically.
       If a companion is missing, you can select it when prompted or continue without it.</p>
    <div class="row">
        <button type="button" id="btnFiles">Add files...</button>
    </div>
    <div id="drop">...or drop the files here</div>
    <input type="file" name="eagle_file[]" id="f" multiple style="display:none">
    <input type="file" id="filesIn" accept=".brd,.sch,.xml" multiple style="display:none">
    <div id="projects"></div>
    <button type="submit" id="btnRender" disabled>Render</button>
</form>

<div id="companionModal" hidden role="dialog" aria-modal="true" aria-labelledby="companionTitle">
    <div id="companionDialog">
        <h2 id="companionTitle">Missing Companion File</h2>
        <p id="companionMessage"></p>
        <p>You can select the missing file, ignore this warning and continue with the available file, or cancel rendering.</p>
        <div class="actions">
            <button type="button" id="companionCancel" class="secondary">Cancel</button>
            <button type="button" id="companionIgnore" class="secondary">Ignore</button>
            <button type="button" id="companionLoad">Load Companion</button>
        </div>
    </div>
</div>
<input type="file" id="companionIn" accept=".brd,.sch" style="display:none">

<?php if ($messages): ?>
<div style="margin-top: 20px;">
    <?php foreach ($messages as $m):
        if (strpos($m, 'error') !== false || strpos($m, 'FAILED') !== false || strpos($m, 'EXCEPTION') !== false) $cls = 'err';
        elseif (strpos($m, 'note:') === 0) $cls = 'warn';
        else $cls = 'ok';
    ?>
        <div class="msg <?= $cls ?>"><?= htmlspecialchars($m) ?></div>
    <?php endforeach; ?>
</div>
<?php endif; ?>

<?php if ($groups_out): ?>
<?php foreach ($groups_out as $gi => $g): ?>
<div class="group" id="grp<?= $gi ?>">
    <b><?= htmlspecialchars($g['base']) ?></b>
    <div class="tabs">
        <?php foreach ($g['items'] as $ii => $it): ?>
            <button type="button" class="tab<?= $ii === 0 ? ' on' : '' ?>" data-g="<?= $gi ?>" data-i="<?= $ii ?>"
                    data-url="<?= htmlspecialchars($it['url']) ?>"><?= htmlspecialchars($it['label']) ?></button>
        <?php endforeach; ?>
        <button type="button" class="fs" data-g="<?= $gi ?>">Fullscreen</button>
        <a id="ext<?= $gi ?>" href="<?= htmlspecialchars($g['items'][0]['url']) ?>" target="_blank">open in new tab</a>
    </div>
    <div class="frames" id="frames<?= $gi ?>">
        <?php foreach ($g['items'] as $ii => $it): ?>
            <iframe id="fr<?= $gi ?>_<?= $ii ?>" data-url="<?= htmlspecialchars($it['url']) ?>"
                    <?= $ii === 0 ? 'class="on" src="' . htmlspecialchars($it['url']) . '"' : '' ?>></iframe>
        <?php endforeach; ?>
    </div>
</div>
<?php endforeach; ?>
<?php endif; ?>

<div class="info">
    <p><b>Pairing:</b> <code>test.sch</code> and <code>test.brd</code> are matched automatically by base name when both
    are selected. Browser security prevents this page from reading an unselected companion file from your disk.
    If a companion is missing, you can load it through the standard file picker, ignore it, or cancel before rendering.
    Browser security prevents automatic reading of an unselected local file. Folder selection is not used.</p>
    <p><b>Privacy:</b> uploaded files are deleted from the server as soon as they are rendered; the generated viewers
    are deleted when you leave or close this page (and, at the latest, after 2 hours).
    Boards have a 2D view with an embedded 3D view (requires a closed outline on layer 20).</p>
    <p>Place <code>three.min.js</code> and <code>TrackballControls.js</code> next to this script (or in <code>output/</code>).</p>
</div>

<script>
const RUN = <?= json_encode($run) ?>;
const MAX_FILES = <?= (int)MAX_UPLOAD_FILES ?>;
const input = document.getElementById('f'), drop = document.getElementById('drop');
const listEl = document.getElementById('projects'), btnRender = document.getElementById('btnRender');
const projects = {};   // lower-case base name -> {name, files: {brd, sch, xml}, checked}

function esc(t) { return t.replace(/[<>&"]/g, ''); }

function render() {
    const dt = new DataTransfer();
    let nFiles = 0;
    listEl.innerHTML = '';
    Object.keys(projects).sort().forEach(key => {
        const p = projects[key], f = p.files;
        const row = document.createElement('div'); row.className = 'proj';
        const cb = document.createElement('input'); cb.type = 'checkbox'; cb.checked = p.checked;
        cb.onchange = () => { p.checked = cb.checked; render(); };
        const lab = document.createElement('label');
        lab.append(cb, ' ' + p.name + '  ');
        const flag = (ext, have) => {
            const s = document.createElement('span');
            s.className = have ? 'ok' : 'no';
            s.textContent = ext.toUpperCase() + (have ? ' \u2713 ' : ' \u2717 ');
            return s;
        };
        row.append(lab);
        if (f.xml) row.append(flag('xml', true));
        else { row.append(flag('sch', !!f.sch)); row.append(flag('brd', !!f.brd)); }
        if (!f.xml && !(f.sch && f.brd)) {
            const m = document.createElement('span'); m.className = 'no';
            m.textContent = '(' + (f.sch ? '.brd' : '.sch') + ' not selected: it will be reported as missing on upload)';
            row.append(m);
        }
        listEl.append(row);
        if (p.checked) Object.values(f).forEach(file => { if (nFiles < MAX_FILES) { dt.items.add(file); nFiles++; } });
    });
    input.files = dt.files;               // only the ticked projects are sent
    btnRender.disabled = nFiles === 0;
}

// fromFolder (a dropped folder): new projects are ticked only when they are few
function addFiles(list) {
    const found = new Set();
    [...list].forEach(f => {
        const m = f.name.match(/^(.*)\.(brd|sch|xml)$/i);
        if (!m) return;
        const key = m[1].toLowerCase();
        const isNew = !projects[key];
        const p = projects[key] = projects[key] || {name: m[1], files: {}, checked: false};
        p.files[m[2].toLowerCase()] = f;
        if (isNew) found.add(key);
    });
    found.forEach(key => { projects[key].checked = true; });
    render();
}

document.getElementById('btnFiles').onclick = () => document.getElementById('filesIn').click();
document.getElementById('filesIn').onchange = e => { addFiles(e.target.files); e.target.value = ''; };

// Universal companion workflow: use the ordinary file picker, supported by all desktop browsers.
const companionModal = document.getElementById('companionModal');
const companionMessage = document.getElementById('companionMessage');
const companionIn = document.getElementById('companionIn');
let pendingCompanion = null;
let bypassCompanionCheck = false;

function getMissingCompanions() {
    const missing = [];
    Object.keys(projects).sort().forEach(key => {
        const p = projects[key];
        if (!p.checked || p.files.xml || (p.files.brd && p.files.sch)) return;
        if (p.files.brd) missing.push({key, name: p.name, ext: 'sch'});
        else if (p.files.sch) missing.push({key, name: p.name, ext: 'brd'});
    });
    return missing;
}

function showCompanionDialog(missing) {
    pendingCompanion = missing[0];
    const names = missing.map(item => item.name + '.' + item.ext);
    companionMessage.textContent = 'The companion file was not selected: ' +
        (names.length === 1 ? names[0] : 'for these projects: ' + names.join(', ')) + '.';
    companionModal.hidden = false;
}

function closeCompanionDialog() {
    companionModal.hidden = true;
    pendingCompanion = null;
}

document.getElementById('companionLoad').addEventListener('click', () => {
    if (pendingCompanion) companionIn.click();
});
document.getElementById('companionIgnore').addEventListener('click', () => {
    closeCompanionDialog();
    bypassCompanionCheck = true;
    document.getElementById('frm').requestSubmit();
});
document.getElementById('companionCancel').addEventListener('click', closeCompanionDialog);

companionIn.addEventListener('change', () => {
    const file = companionIn.files && companionIn.files[0];
    if (!file || !pendingCompanion) {
        companionIn.value = '';
        return;
    }
    const expected = (pendingCompanion.name + '.' + pendingCompanion.ext).toLowerCase();
    if (file.name.toLowerCase() !== expected) {
        companionIn.value = '';
        window.alert('You selected "' + file.name + '". The required file is "' + expected + '".');
        companionIn.click();
        return;
    }
    addFiles([file]);
    companionIn.value = '';
    closeCompanionDialog();
    // Check again on submit; if another project is incomplete, it will be handled next.
    document.getElementById('frm').requestSubmit();
});

document.getElementById('frm').addEventListener('submit', ev => {
    if (bypassCompanionCheck) {
        bypassCompanionCheck = false;
        return;
    }
    const missing = getMissingCompanions();
    if (missing.length) {
        ev.preventDefault();
        showCompanionDialog(missing);
    }
});

// File-only drag and drop. Directory traversal is intentionally disabled.
drop.addEventListener('drop', ev => {
    const files = [...(ev.dataTransfer.files || [])].filter(f => /\.(brd|sch|xml)$/i.test(f.name));
    addFiles(files);
});

// Results: tabs switch the iframe of a project; the other viewer is loaded the first time its tab is opened
document.querySelectorAll('.tab').forEach(b => b.onclick = () => {
    const gi = b.dataset.g, ii = b.dataset.i;
    document.querySelectorAll('#grp' + gi + ' .tab').forEach(x => x.classList.toggle('on', x === b));
    document.querySelectorAll('#frames' + gi + ' iframe').forEach(fr => {
        const on = fr.id === 'fr' + gi + '_' + ii;
        fr.classList.toggle('on', on);
        if (!on) return;
        if (!fr.getAttribute('src')) fr.src = fr.dataset.url;
        else { try { fr.contentWindow.dispatchEvent(new Event('resize')); } catch (e) {} }
    });
    document.getElementById('ext' + gi).href = b.dataset.url;
});
document.querySelectorAll('.fs').forEach(b => b.onclick = () => {
    const el = document.getElementById('frames' + b.dataset.g);
    if (el.requestFullscreen) el.requestFullscreen();
});

// Leaving or closing the page deletes the server-side run folder right away
window.addEventListener('pagehide', e => {
    if (!RUN || e.persisted) return;
    const fd = new FormData();
    fd.append('action', 'cleanup'); fd.append('run', RUN);
    navigator.sendBeacon(location.pathname, fd);
});
</script>
</body>
</html>
