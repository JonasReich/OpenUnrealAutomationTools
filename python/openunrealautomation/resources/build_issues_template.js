// This inline json string will be replaced with the actual json by our Python script that searches for the capitalized variable name
let inline_json = String.raw`INLINE_JSON`;

// ----- GLOBALS -----
let CODE_CONTAINER_TEMPLATE = `<div class="text-nowrap overflow-scroll mx-3 p-3 code-container"><div>`;
let tags_and_labels = FILTER_TAGS_AND_LABELS;

var filter = {
    tags: new Set(),
    strings: new Map()
};
var last_goto_lines = new Map();

// #TODO Make this automatic -> Collect item values automatically, so we can just call addButtonsForData("Developer")
let all_devs = new Set();
let tag_counts = new Map();

let chart_colors = [
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb"
];

let string_var_prefixes = new Map();
string_var_prefixes.set("Developer", "👤");

// map variable name to values to counts
// e.g.
/*
{
    "variable_name" : {
        "value_1" : 10,
        "value_2" : 30
    }
}
*/
let string_vars = new Map();

// ----- GLOBALS -----

const zeroPad = (num, places) => String(num).padStart(places, '0');
function getTagLabel(tag) {
    return tags_and_labels[tag] ?? tag;
}

function goToSource(source_file, line) {
    let new_goto_line = `#source-log-${source_file}-${line}`;
    let last_goto_line = last_goto_lines.has(source_file) ? last_goto_lines.get(source_file) : null;
    if (last_goto_line === null) {
        // do nothing
    } else {
        $(last_goto_line).removeClass("highlight-line");
    }
    $(new_goto_line).addClass("highlight-line");
    window.location = new_goto_line;
    // This does not work properly :/
    // $('html,body').animate({ scrollTop: $(new_goto_line).offset().top }, 500);
    last_goto_lines.set(source_file, new_goto_line);
}



function increment_map_counter(map, key) {
    if (map.has(key)) {
        map.set(key, map.get(key) + 1);
    } else {
        map.set(key, 1);
    }
}
function increment_tag_count(tag) {
    increment_map_counter(tag_counts, tag);
}

function incrementStringVar(key, value) {
    if (!string_vars.has(key)) {
        string_vars.set(key, new Map());
    }
    let inner_map = string_vars.get(key);
    if (inner_map.has(value)) {
        inner_map.set(value, inner_map.get(value) + 1);
    } else {
        inner_map.set(value, 1);
    }
}


function updateSeverityCSS(element, severity) {
    let is_error = severity == "error";
    let is_warning = severity == "warning";
    let is_severe_warning = severity == "severe_warning";
    let is_message = !is_error && !is_warning && !is_severe_warning;

    element.toggleClass("warning", is_warning);
    element.toggleClass("severe-warning", is_severe_warning);
    element.toggleClass("error", is_error);
    element.toggleClass("message", is_message);
}


function addLineDiv(line_obj, source_file, line_name = "") {
    let line_str = line_obj.line;

    // let file_path_matches = line_str.match(/([\\\/\w\.]+:?[\/\\][\\\/\w\.]+)/g, "");
    // if (file_path_matches) {
    //     for (let i = 0; i < file_path_matches.length; i++) {
    //         let file_path = file_path_matches[i];
    //         // This only works if the paths do not have any overlaps.
    //         // With this implementation, 'foo/bar/baz' and 'foo/bar' in the same log line would cause the 'foo/bar' part to overlap, which can result in wrong text resplacement / invalid HTML
    //         line_str = line_str.replace(file_path, `<a onclick="navigator.clipboard.writeText('${file_path.replace("\\", "\\\\")}')" class="file-path code-tag">${file_path}</a>`);
    //     }
    // }

    // Line numbers in report start with 0
    let normal_line_nr = line_obj.line_nr + 1;
    let jump_to_src_btn = `<button class="btn-xs btn-secondary" style="font-size: 0.6em; margin-right: 1em;" onclick="goToSource('${source_file}', ${normal_line_nr})">🔗</button>`
    let new_code_line = $(`${line_name} <code>${jump_to_src_btn}<div class="code-tag">${zeroPad(line_obj.occurences)}x (1st at line ${zeroPad(normal_line_nr, 5)}): </div>${line_str}<br></code>`);
    new_code_line.data("json", line_obj);
    new_code_line.data("source_file", source_file);
    
    for (tag_idx in line_obj.tags) {
        let tag = line_obj.tags[tag_idx];
        increment_tag_count(tag);
        new_code_line.find(".code-tag").prepend(createTagButton(tag, false));
    }

    let line_string_vars = line_obj.strings;

    for (string_key in line_string_vars) {
        let string_value = line_string_vars[string_key];
        incrementStringVar(string_key, string_value);
        new_code_line.find(".code-tag").prepend(createStringVarFilterButton(string_key, string_value, false));
    }

    let tagged_dev = line_string_vars["Developer"] ?? "";
    all_devs.add(tagged_dev);

    updateSeverityCSS(new_code_line, line_obj.severity);

    return new_code_line;
}

function addMatchListCodeContainer(match_list, parent) {
    match_list_row = $(`<details class="row issue-scope pt-2"><summary>${name}</summary>${CODE_CONTAINER_TEMPLATE}</details>`);
    match_list_row.data("name", name);
    parent.append(match_list_row);
    match_list_row.data("json", match_list);

    if (match_list.hidden) {
        match_list_row.hide();
    }

    updateSeverityCSS(match_list_row, match_list.severity);

    return match_list_row.find(".code-container");
}

function addIssueScope(source_file, scope, ref_node) {
    // #TODO adjust css classes
    let scope_row = $(`<div class="row scope-container scope-${scope.status} pt-2 px-4"><div>${scope.name}</div></div>`);
    $(ref_node).append(scope_row);

    if ((typeof scope.start === 'string' || scope.start instanceof String) == false && scope.start.severity != "message") {
        let start_code_line = addLineDiv(scope.start, source_file, "Start");
        scope_row.append($(CODE_CONTAINER_TEMPLATE).append(start_code_line));
    }

    scope.match_lists.forEach(match_list => {
        let code_container = addMatchListCodeContainer(match_list, scope_row);

        for (let line_idx = 0; line_idx < match_list.lines.length; line_idx++) {
            let line_obj = match_list.lines[line_idx];
            let new_code_line = addLineDiv(line_obj, source_file);
            code_container.append(new_code_line);
        }
    });

    scope.child_scopes.forEach(child_scope => {
        addIssueScope(source_file, child_scope, scope_row);
    });

    if ((typeof scope.end === 'string' || scope.end instanceof String) == false && scope.end.severity != "message") {
        let end_code_line = addLineDiv(scope.end, source_file, "End");
        scope_row.append($(CODE_CONTAINER_TEMPLATE).append(end_code_line));
    }
}

let json_obj = JSON.parse(inline_json);
console.log(json_obj);
for (const [source_file, scope] of Object.entries(json_obj)) {
    addIssueScope(source_file, scope, $("#code-root")[0]);
}

function updateScopeCounters() {
    $(".issue-scope").each(function () {
        if ($(this).data("json").hidden) {
            $(this).hide();
            return;
        }
        num_children = 0;
        num_active_children = 0;
        $(this).find("code").each(function () {
            num_children++;
            if ($(this).css("display") != "none")
                num_active_children++;
        })

        summary = $(this).find("summary");
        json_data = $(this).data("json");

        let tag_label_str = "";
        let first_label = true;
        for (let tag_idx = 0; tag_idx < json_data.tags.length; tag_idx++) {
            let tag = json_data.tags[tag_idx];
            if (!first_label)
                tag_label_str += ", ";
            first_label = false;
            tag_label_str += getTagLabel(tag);
        }

        summary.text(json_data.name + ` (${num_active_children}/${num_children})`);
        $(this).toggle(num_active_children > 0);
    })
}
updateScopeCounters();

function resetFilter() {
    filter.tags.clear();
    filter.strings.clear();

    $("#code-root code").show();
    // Reset all filter buttons
    $(".filter-btn").toggleClass("btn-primary", false);
    $(".filter-btn").toggleClass("btn-secondary", true);
}

function applyFilter() {
    $("#code-root code").each(function () {
        let tags = $(this).data("json")["tags"];
        let has_all_tags = true;
        for (const filter_tag of filter.tags.keys()) {
            if (tags.includes(filter_tag) == false) {
                has_all_tags = false;
            }
        }
        if (!has_all_tags) {
            $(this).toggle(false);
            return;
        }
        let has_all_strings = true;
        for (const [string_var, string_value] of filter.strings.entries()) {
            let item_string_value = $(this).data("json").strings[string_var];
            if (item_string_value != string_value) {
                has_all_strings = false;
            }
        }
        $(this).toggle(has_all_strings);
    });

    updateScopeCounters();
}

let show_all_button = $("#show-all-btn");
$(show_all_button).click(function () {
    resetFilter();

    // Set show all button to primary (blue)
    $("#show-all-btn").toggleClass("btn-primary", true);
    $("#show-all-btn").toggleClass("btn-secondary", false);

    updateScopeCounters();
})
$("#filter-btns").append(show_all_button);

$("#filter-btns").append($("<div class='m-2'/>"));

function filterTags(tag) {
    let filter_now = filter.tags.has(tag) == false;
    if (filter_now) {
        filter.tags.add(tag);
    } else {
        filter.tags.delete(tag);
    }

    $("#show-all-btn").toggleClass("btn-primary", false);
    $("#show-all-btn").toggleClass("btn-secondary", true);

    $(".tag-btn").each(function () {
        let btn_tag = $(this).data("tag");
        if (btn_tag == tag) {
            $(this).toggleClass("btn-primary", filter_now);
            $(this).toggleClass("btn-secondary", !filter_now);
        }
    });
    applyFilter();
}

function createTagButton(tag, add_count) {
    let tag_count = tag_counts.has(tag) ? tag_counts.get(tag) : 0;
    let count_suffix = add_count ? ` (${tag_count})` : "";
    let tag_button = $(`<button class="btn badge rounded-pill btn-secondary filter-btn tag-btn">${getTagLabel(tag)}${count_suffix}</button>`);
    tag_button.data("tag", tag);
    $(tag_button).click(function () { filterTags(tag) });
    return tag_button
}

// Add buttons
// #TODO this is hardcoded -> need to make dynamic but still have all POSSIBLE tags
for (let [tag, label] of Object.entries(tags_and_labels)) {
    $("#filter-btns").append(createTagButton(tag, true));
}

$("#filter-btns").append($("<div class='m-2'/>"));

function filterStringData(string_var, string_value) {
    let filter_now = true;
    if (filter.strings.has(string_var)) {
        if (filter.strings.get(string_var) == string_value) {
            filter.strings.delete(string_var);
            filter_now = false;
        }
    }
    if (filter_now) {
        filter.strings.set(string_var, string_value);
    }

    $("#show-all-btn").toggleClass("btn-primary", false);
    $("#show-all-btn").toggleClass("btn-secondary", true);

    $(".string-filter-btn").each(function () {
        let item = $(this).data(string_var);
        if (item == string_value) {
            $(this).toggleClass("btn-primary", filter_now);
            $(this).toggleClass("btn-secondary", !filter_now);
        } else {
            // developer buttons are mutually exclusive
            $(this).toggleClass("btn-primary", false);
            $(this).toggleClass("btn-secondary", true);
        }
    });
    applyFilter();
}

function createStringVarFilterButton(string_var, string_value, display_count) {
    let value_count = string_vars.get(string_var).get(string_value);
    let button_prefix = string_var_prefixes.has(string_var) ? string_var_prefixes.get(string_var) : "";
    let count_str_suffix = display_count ? ` (${value_count})` : "";
    let button = $(`<button class="btn btn-sm btn-secondary filter-btn string-filter-btn badge rounded">${button_prefix} ${string_value}${count_str_suffix}</button>`);
    button.data(string_var, string_value);
    $(button).click(function () { filterStringData(string_var, string_value) });
    return button;
}

function addFilterButtonForStringVar(string_var, string_var_items) {
    string_var_items.forEach(function (item) {
        if (item == "") return;
        let button = createStringVarFilterButton(string_var, item, true);
        $("#filter-btns").append(button);
    })
}

addFilterButtonForStringVar("Developer", all_devs);

//---------------------------
// STATS

// Craete a chart canvas context
function createChartContext() {
    let canvasRoot = $("#stats-chart-root")[0];
    var canvasTemplate = '<canvas id="stats-chart" class="p-2 m-3 bg-dark"></canvas>';
    let canvas = $(canvasTemplate).appendTo(canvasRoot)[0];
    $(canvas).css("display", "inline-block");
    return canvas.getContext('2d');
}

function createIssuesPerTagChart() {
    let labels = [];
    let error_counts = [];
    let warning_counts = [];
    let severe_warning_counts = [];
    let message_counts = [];

    let error_counts_total = [];
    let warning_counts_total = [];
    let severe_warning_counts_total = [];
    let message_counts_total = [];

    // #TODO instead of counting occurences manually, the json export should contain tag data incl. unique tag occurences + total tag occurences
    tag_counts.forEach(function (count, tag) {
        labels.push(getTagLabel(tag));
        let error_count = 0;
        let warning_count = 0;
        let severe_warning_count = 0;
        let message_count = 0;
        let error_count_total = 0;
        let warning_count_total = 0;
        let severe_warning_count_total = 0;
        let message_count_total = 0;
        count = $("#code-root code").each(function () {
            if ($(this).data("json").tags.includes(tag) == false) {
                return;
            }
            if ($(this).data("json").severity == "error") {
                error_count++;
                error_count_total += $(this).data("json").occurences;
            } else if ($(this).data("json").severity == "warning") {
                warning_count++;
                warning_count_total += $(this).data("json").occurences;
            } else if ($(this).data("json").severity == "severe_warning") {
                severe_warning_count++;
                severe_warning_count_total += $(this).data("json").occurences;
            } else {
                message_count++;
                message_count_total += $(this).data("json").occurences;
            }
        })
        error_counts.push(error_count);
        warning_counts.push(warning_count);
        severe_warning_counts.push(severe_warning_count);
        message_counts.push(message_count);
        error_counts_total.push(error_count_total);
        warning_counts_total.push(warning_count_total);
        severe_warning_counts_total.push(severe_warning_count_total);
        message_counts_total.push(message_count_total);
    })

    function createIssueCountChart(title, error_counts_var, warning_counts_var, severe_warning_counts_var, message_counts_var) {
        new Chart(createChartContext(), {
            type: "bar",
            data: {
                labels: labels,
                datasets: [
                    { label: "Errors", data: error_counts_var, backgroundColor: "#bb4444", color: "#bb4444" },
                    { label: "Warnigns", data: warning_counts_var, backgroundColor: "#bbbb44", color: "#bbbb44" },
                    { label: "Severe Warnigns", data: severe_warning_counts_var, backgroundColor: "#e9a00f", color: "#e9a00f" },
                    { label: "Messages", data: message_counts_var, backgroundColor: "#aaaaaa", color: "#aaaaaa" }
                ]
            },
            options: {
                color: "white",
                backgroundColor: "transparent",
                plugins: {
                    title: { display: true, text: title }
                }
            }
        });
    }

    createIssueCountChart("Issues per Tag (Unique)", error_counts, warning_counts, severe_warning_counts, message_counts);
    createIssueCountChart("Issues per Tag (Total)", error_counts_total, warning_counts_total, severe_warning_counts_total, message_counts_total);
}
createIssuesPerTagChart()

const ChartPreset = {
    BAR: "bar",
    BAR_HORIZONTAL: "barh",
    LINE: "line",
    PIE: "pie"
};

// Create a dynamic chart based on numerics data
// item_key_variable is the string variable name to use as label for data points
// stats are the individual numerics -> 1 data set per stat
// lables are display names for the data sets
function createNumericsChart(preset, chart_title, item_key_variable, stats, labels) {
    let datamap = new Map();
    let datasets = [];
    let item_labels = [];

    for (let i = 0; i < stats.length; i++) {
        const stat = stats[i];
        let data = [];
        let code_idx = 0;
        $("#code-root code").each(function (index, element) {
            const json = $(this).data("json");
            let datapoint_key = json.strings[item_key_variable];
            if (datapoint_key === undefined) {
                return;
            }

            const data_point = json.numerics[stat];
            item_labels.length = Math.max(item_labels.length, code_idx + 1);
            item_labels[code_idx] = datapoint_key;
            data.push(data_point);
            code_idx++;
        })
        const color = preset == ChartPreset.PIE ? chart_colors : chart_colors[i];
        const label = labels[i];
        datasets.push({
            label: label,
            data: data,
            backgroundColor: color,
            color: color,
            borderColor: color,
            //borderWidth: 1
        });
    }

    let type = "bar";
    switch (preset) {
        case ChartPreset.BAR:
        case ChartPreset.BAR_HORIZONTAL:
            type = "bar"
            break
        case ChartPreset.LINE:
            type = "line"
            break
        case ChartPreset.PIE:
            type = "pie"
            break
    }
    let indexAxis = (preset == ChartPreset.BAR_HORIZONTAL ? 'y' : 'x');

    new Chart(createChartContext(), {
        type: type,
        data: {
            labels: Array.from(item_labels),
            datasets: datasets
        },
        options: {
            color: "white",
            backgroundColor: "transparent",
            indexAxis: indexAxis,
            plugins: {
                title: {
                    display: true,
                    text: chart_title
                }
            }
        }
    });
}
let ddc_stats = ["DDC_TotalTime", "DDC_GameThreadTime", "DDC_AssetNum", "DDC_MB"];
let ddc_labels = ["Total Time", "Game Thread Time", "Asset Number", "MB"];
createNumericsChart(ChartPreset.LINE, "DDC Resource Stats", "DDC_Key", ddc_stats, ddc_labels);

createNumericsChart(ChartPreset.PIE, "UAT Command Times", "UAT_Command", ["Duration"], ["Duration"]);
// No good way to display exit codes in a chart
// createNumericsChart(ChartPreset.LINE_HORIZONTAL, "UAT Commands", "UAT_Command", ["ExitCode"], ["ExitCode"])