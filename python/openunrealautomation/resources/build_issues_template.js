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

let all_lines = [];
let all_files = [];

// #TODO Make this automatic -> Collect item values automatically, so we can just call addButtonsForData("Developer")
let all_devs = new Set();
let tag_counts = new Map();

let chart_colors = [
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",

    // -- repeat. not ideal may need to be replaced with actual colors
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",
    //...
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",
    //...
    "#bb4444",
    "#44bb44",
    "#4444bb",
    "#bbbb44",
    "#44bbbb",
    "#bb44bb",
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
    // show / expand source container
    $(new_goto_line).closest(".source-log-container").show().prev(".btn-expand-source-container").hide();

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

function expandSourceContainer(button) {
    $(button).next(".source-log-container").show();
    $(button).hide();
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

    // Add clickable links to assets (click -> copy to clipboard)
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
    let new_code_line = $(`${line_name} <code>${jump_to_src_btn}<div class="code-tag">${zeroPad(line_obj.occurences)}x #1@ ${zeroPad(normal_line_nr, 5)} </div>${line_str}<br></code>`);
    new_code_line.data("json", line_obj);
    new_code_line.data("source_file", source_file);
    
    for (tag_idx in line_obj.tags) {
        let tag = line_obj.tags[tag_idx];
        increment_tag_count(tag);
        // Tags are usually added per category so we shouldn't need buttons per line.
        // Only current exception: Department tags of last detected dev 
        //new_code_line.find(".code-tag").prepend(createTagButton(tag, false));
    }

    let line_string_vars = line_obj.strings;

    let string_vars_with_filter_btns = ["Developer"];

    for (string_key in line_string_vars) {
        if (string_vars_with_filter_btns.includes(string_key))
        {
            let string_value = line_string_vars[string_key];
            incrementStringVar(string_key, string_value);
            new_code_line.find(".code-tag").prepend(createStringVarFilterButton(string_key, string_value, false));
        }
    }

    let tagged_dev = line_string_vars["Developer"] ?? "";
    all_devs.add(tagged_dev);

    updateSeverityCSS(new_code_line, line_obj.severity);

    return new_code_line;
}

function addMatchListCodeContainer(match_list, parent) {
    match_list_row = $(`<details class="row issue-scope pt-2"><summary class="issue-scope-summary">${name}</summary>${CODE_CONTAINER_TEMPLATE}</details>`);
    match_list_row.data("name", name);
    parent.append(match_list_row);
    match_list_row.data("json", match_list);

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
        let code_container = null;
        if (match_list.hidden == false)
        {
            code_container = addMatchListCodeContainer(match_list, scope_row);
        }

        for (let line_idx = 0; line_idx < match_list.lines.length; line_idx++) {
            let line_obj = match_list.lines[line_idx];
            line_obj.source_scope = scope;
            line_obj.source_file = source_file;
            all_lines.push(line_obj);
            
            if (match_list.hidden == false)
            {
                let new_code_line = addLineDiv(line_obj, source_file);

                if ("GroupBy" in line_obj.strings)
                {
                    let group_by_name = line_obj.strings["GroupBy"];
                    let group_by_name_data = `data-line-group-by='${group_by_name}'`
                    let group_root = code_container.find(`.line-group[${group_by_name_data}]`);
                    if (group_root.length == 0)
                    {
                        let new_line_group = $(`<details class='line-group' ${group_by_name_data}><summary class='line-group-summary'>${group_by_name}</summary></details>`);
                        new_line_group.data("name", group_by_name);
                        code_container.append(new_line_group);
                    }

                    code_container.find(`.line-group[${group_by_name_data}]`).append(new_code_line);
                }
                else
                {
                    code_container.append(new_code_line);
                }
            }
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
for (const [source_file, root_scope] of Object.entries(json_obj)) {
    all_files.push(source_file);
    let code_root =  $(`#${source_file}_code-summary`)[0];
    addIssueScope(source_file, root_scope, code_root);
}

function updateScopeCounters() {
    $(".issue-scope").each(function () {
        num_children = 0;
        num_active_children = 0;
        $(this).find("code").each(function () {
            num_children++;
            if ($(this).css("display") != "none")
                num_active_children++;
        })

        summary = $(this).find(".issue-scope-summary");
        json_data = $(this).data("json");

        summary.html("<span class='px-2'>" + json_data.name + ` (${num_active_children}/${num_children})` + "</span>");
        $(this).toggle(num_active_children > 0);

        for (let tag_idx = 0; tag_idx < json_data.tags.length; tag_idx++) {
            let tag = json_data.tags[tag_idx];
            $(summary).append(createTagButton(tag, false));
        }
    })
    $(".line-group").each(function () {
        num_children = 0;
        num_active_children = 0;
        $(this).find("code").each(function () {
            num_children++;
            if ($(this).css("display") != "none")
                num_active_children++;
        })

        summary = $(this).find(".line-group-summary");
        line_group_name = $(this).data("name");

        summary.html("<span class='px-2'>" + line_group_name + ` (${num_active_children}/${num_children})` + "</span>");
        $(this).toggle(num_active_children > 0);
    })
}
updateScopeCounters();

function resetFilter() {
    filter.tags.clear();
    filter.strings.clear();

    $(".code-summary code").show();
    // Reset all filter buttons
    $(".filter-btn").toggleClass("btn-primary", false);
    $(".filter-btn").toggleClass("btn-secondary", true);
}

function applyFilter() {
    $(".code-summary code").each(function () {
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

function filterTags(tag) {
    let filter_now = filter.tags.has(tag) == false;
    if (filter_now) {
        filter.tags.add(tag);
    } else {
        filter.tags.delete(tag);
    }

    $("#show-all-btn").toggleClass("btn-primary", false);
    $("#show-all-btn").toggleClass("btn-secondary", true);

    applyFilter();

    $(".tag-btn").each(function () {
        let btn_tag = $(this).data("tag");
        if (btn_tag == tag) {
            $(this).toggleClass("btn-primary", filter_now);
            $(this).toggleClass("btn-secondary", !filter_now);
        }
    });
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

function getStatsRoot() {
    return $("#stats-chart-root")[0];
}

// Craete a chart canvas context
function createChartJsContext() {
    let canvasRoot = getStatsRoot();
    var canvasTemplate = '<canvas class="stats-chart p-2 mb-2 bg-dark"></canvas>';
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
        count = $(".code-summary code").each(function () {
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
        new Chart(createChartJsContext(), {
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
function getChartTypeStr(preset) {
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
    return type;
}

function createNumericsChart(preset, chart_title, datasets, item_labels) {
    let indexAxis = (preset == ChartPreset.BAR_HORIZONTAL ? 'y' : 'x');
    new Chart(createChartJsContext(), {
        type: getChartTypeStr(preset),
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

// Create a dynamic chart based on numerics data
// item_key_variable is the string variable name to use as label for data points
// stats are the individual numerics -> 1 data set per stat
// lables are display names for the data sets
function createNumericsChartFromJsonData(preset, chart_title, item_key_variable, stats, labels, file) {
    let datasets = [];
    let item_labels = [];
    let has_min_1_datapoint = false;

    for (let i = 0; i < stats.length; i++) {
        const stat = stats[i];
        let data = [];
        let code_idx = 0;
        all_lines.forEach(function (json) {
            if (json.source_file != file) {
                return;
            }

            let datapoint_key = json.strings[item_key_variable];
            if (datapoint_key === undefined) {
                return;
            }

            const data_point = json.numerics[stat];
            item_labels.length = Math.max(item_labels.length, code_idx + 1);
            item_labels[code_idx] = datapoint_key;
            data.push(data_point);
            code_idx++;
            has_min_1_datapoint = true;
        })
        const color = preset == ChartPreset.PIE ? chart_colors : chart_colors[i];
        const label = labels[i];
        datasets.push({
            label: label,
            data: data,
            backgroundColor: color,
            color: color,
            borderColor: color
        });
    }

    if (has_min_1_datapoint == false) {
        // This made more sense when we had a single log file. With multiple files, not all of which contain cook steps, this warning is misleading / useless.
        // $(getStatsRoot()).append(`<div><i>No datapoints for '${chart_title}' chart</i></div>`);
        return;
    }

    createNumericsChart(preset, chart_title, datasets, item_labels);
}
let ddc_stats = ["DDC_TotalTime", "DDC_GameThreadTime", "DDC_AssetNum", "DDC_MB"];
let ddc_labels = ["Total Time", "Game Thread Time", "Asset Number", "MB"];
all_files.forEach(function (file){
    createNumericsChartFromJsonData(ChartPreset.LINE, "DDC Resource Stats " + file, "DDC_Key", ddc_stats, ddc_labels, file);
});
all_files.forEach(function (file){
    // createNumericsChartFromJsonData(ChartPreset.PIE, "UAT Command Times " + file, "UAT_Command", ["Duration"], ["Duration"], file);
});

function createCsvChart(preset, chart_title, csv_str) {
    let datasets = [];
    let item_labels = [];

    let csv_rows = csv_str.split('\n');
    let csv_array = csv_rows.map(col => col.split(','));
    let csv_header_row = csv_rows[0].split(',');

    let num_cols = csv_header_row.length;
    let num_rows = csv_rows.length;

    for (let col_idx = 0; col_idx < num_cols; col_idx++) {
        let data = [];
        for (let row_idx = 1; row_idx < num_rows; row_idx++) {
            let datapoint = csv_array[row_idx][col_idx];
            data.push(datapoint);
        }

        if (col_idx == 0) {
            item_labels = data;
            continue;
        }

        let data_label = csv_array[0][col_idx];
        const color = preset == ChartPreset.PIE ? chart_colors : chart_colors[col_idx];
        datasets.push({
            label: data_label,
            data: data,
            backgroundColor: color,
            color: color,
            borderColor: color
        });
    }
    
    createNumericsChart(preset, chart_title, datasets, item_labels);
}
