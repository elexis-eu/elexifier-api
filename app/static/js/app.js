function generateUUID() {
    let d = new Date().getTime();
    let uuid = 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        let r = (d + Math.random()*16)%16 | 0;
        d = Math.floor(d/16);
        return (c=='x' ? r : (r&0x3|0x8)).toString(16);
    });
    return uuid;
}

function new_sel() {
    return {
	type: "xpath",
	supertype: "selector",
	expr: null,
	uuid: generateUUID()
    }
}

function new_xfm() {
    return {
	type: "simple",
	supertype: "transformer",
	selector: new_sel(),
	attr_type: null,
	attr: null,
	rex: null,
	rexGroup: null,
	"const": null,
	uuid: generateUUID()
    }
}

function transform_new_element(ety) {
    if ((ety == 'entry') || (ety == 'sense')) {
	return new_sel();
    } else {
	return new_xfm();
    }
}

function get_slots_list() {
    return ['entry', 'sense', 'def', 'entry_lang', 'hw', 'hw_tr', 'hw_tr_lang', 'ex', 'ex_tr', 'ex_tr_lang'];
}

function transform_new() {
    let etys = get_slots_list();
    let ttemplate = {};
    for (let i=0; i < etys.length; i++) {
	let ety = etys[i];
	ttemplate[ety] = transform_new_element(ety);
    }
/*
    let ttemplate = {
	entry: new_sel(),
	sense: new_sel(),
	entry_lang: new_xfm(),
	hw: new_xfm(),
	hw_tr: new_xfm(),
	hw_tr_lang: new_xfm(),
	ex: new_xfm(),
	ex_tr: new_xfm(),
	ex_tr_lang: new_xfm()
    }
*/
    return ttemplate;
}

function fixup_selector(s) {
    s.supertype = 'selector';
    if (!s.hasOwnProperty('uuid')) {
	s.uuid = generateUUID();
    }
    if (s.type === 'union') {
	s.selectors.forEach((item,index) => {
	    fixup_selector(item);
	});
    }
    if (s.type === 'exclude') {
	fixup_selector(s.left);
	fixup_selector(s.right);
    }
}

function fixup_transformer(t) {
    t.supertype = 'transformer';
    if (!t.hasOwnProperty('uuid')) {
	t.uuid = generateUUID();
    }
    if (t.type === 'simple') { 
	['attr', 'attr_type', 'rex', 'rexGroup', 'const'].forEach((v,idx) => {
	    if (!t.hasOwnProperty(v)) {
		t[v] = null;
	    }
	});
	
	if (t.attr === '{http://elex.is/wp1/teiLex0Mapper/meta}innerText') { 
	    t.attr_type = 'xao_inner';
	    t.attr = null;
	} else if (t.attr === '{http://elex.is/wp1/teiLex0Mapper/meta}innerTextRec') {
	    t.attr_type = 'xao_subtree';
	    t.attr = null;
	} else if (t.attr === '{http://elex.is/wp1/teiLex0Mapper/meta}constant') {
	    t.attr_type = 'xao_const';
	    t.attr = null;
	} else if (t.attr && t.attr.length > 0) {
	    t.attr_type = 'xao_attr';
	    // t.attr is correct
	} else {
	    t.attr_type = 'xao_none';
	}

	fixup_selector(t.selector);
    } else if (t.type === 'dummy') {
	fixup_selector(t.selector);
    } else if (t.type === 'union') {
	t.transformers.forEach((item,index) => {
	    fixup_transformer(item);
	});
    }
}

function transform_db_to_js(t) {
    if (!t) {
	// return a new template
	return transform_db_to_js(transform_new());
    } else {
	t.slots = get_slots_list(); // ['entry', 'sense', 'def', 'entry_lang', 'hw', 'hw_tr', 'hw_tr_lang', 'ex', 'ex_tr', 'ex_tr_lang'];

	t.supertype = 'transform_spec';

	// wrap entry and sense if needed
	if (!('entry' in t)) t.entry = transform_new_element('entry');
	if (!(t.entry.type === 'dummy')) {
	    let entry_tmp = t.entry;
	    t.entry = {
		type: "dummy",
		selector: entry_tmp,
		uuid: generateUUID()
	    };
	}
	if (!('sense' in t)) t.sense = transform_new_element('sense');
	if (!(t.sense.type === 'dummy')) {
	    let sense_tmp = t.sense;
	    t.sense = {
		type: "dummy",
		selector: sense_tmp,
		uuid: generateUUID()
	    };
	}

	t.slots.forEach((v,idx) => {
	    if (!t.hasOwnProperty(v)) {
		t[v] = transform_new_element(v); //new_xfm();
	    }
	    fixup_transformer(t[v]);
	});

	return t;
    }
}

function transform_js_to_db_node(n) {
    if (n.supertype === 'selector') {
	if (n.type === 'xpath') {
	    if (!n.expr) return null;
	} else if (n.type === 'union') {
	    let nu = [];
	    for (let i=0;i<n.selectors.length;i++) {
		let r = transform_js_to_db_node(n.selectors[i]);
		if (r) nu.push(r);
	    }
	    n.selectors = nu;
	    if (n.selectors.length == 0) return null;
	} else if (n.type === 'exclude') {
	    let tl = transform_js_to_db_node(n.left);
	    let tr = transform_js_to_db_node(n.right);
	    if (!tl || !tr) return null;
	}
    } else if (n.supertype === 'transformer') {
	if (n.type === 'simple' || n.type === 'dummy') {
	    switch (n.attr_type) {
		case 'xao_none':
		return null;
		break;
		case 'xao_attr':
		break;
		case 'xao_const':
		n.attr = '{http://elex.is/wp1/teiLex0Mapper/meta}constant';
		break;
		case 'xao_inner':
		n.attr = '{http://elex.is/wp1/teiLex0Mapper/meta}innerText';
		break;
		case 'xao_subtree':
		n.attr = '{http://elex.is/wp1/teiLex0Mapper/meta}innerTextRec';
		break;
	    }
	    delete n.attr_type;
	    let r = transform_js_to_db_node(n.selector);
	    if (!r) return null;
	} else if (n.type === 'union') {
	    let nu = [];
	    for (let i=0;i<n.transformers.length;i++) {
		let r = transform_js_to_db_node(n.transformers[i]);
		if (r) nu.push(r);
	    }
	    n.transformers = nu;
	    if (n.transformers.length == 0) return null;
	    // !!! this should devolve union transformer with one element into a simple transformer, but it won't for now...
	}
    }
    return n;
}

function transform_js_to_db(t) {
    let ret = JSON.parse(JSON.stringify(t));
    for (let i=0;i<ret.slots.length;i++) {
	let slot = ret.slots[i];
	let rv = transform_js_to_db_node(ret[slot]);
	if (!rv) delete ret[slot];
    }
    return ret;
}

function maybe_parent(u, n, t) {
    if (u.parent == null) {
	u.parent = n;
	u.parent_type = t;
    }
    return u;
}

function find_node_sel(uuid, n) {
    if (n.uuid === uuid) {
	return { node: n, parent: null, parent_type: null };
    } else {
	if (n.type === 'xpath') {
	} else if (n.type === 'exclude') {
	    let u = null;
	    u = find_node_sel(uuid, n.left);
	    if (u) return maybe_parent(u, n, 'sel-el');
	    u = find_node_sel(uuid, n.right);
	    if (u) return maybe_parent(u, n, 'sel-er');
	} else if (n.type === 'union') {
	    for (let i=0; i< n.selectors.length; i++) {
		let u = find_node_sel(uuid, n.selectors[i]);
		if (u) {
		    u.parent_idx = i;
		    return maybe_parent(u,n, 'sel-u');
		}
	    }
	}
	return null;
    }
}

function find_node_xfm(uuid, n) {
    if (n.uuid === uuid) {
	return { node: n, parent: null, parent_type: null };
    } else {
	if (n.type === 'dummy' || n.type === 'simple') {
	    let u = find_node_sel(uuid, n.selector);
	    if (u) return maybe_parent(u, n, 'xfm');
	} else if (n.type === 'union') {
	    for (let i=0; i<n.transformers.length; i++) {
		let u = find_node_xfm(uuid, n.transformers[i]);
		if (u) {
		    u.parent_idx = i;
		    return maybe_parent(u, n, 'xfm-u');
		}
	    }
	}
	return null;
    }
}

function find_node(uuid, ts) {
    const vars = ['def', 'entry', 'sense', 'entry_lang', 'hw', 'hw_tr', 'hw_tr_lang', 'ex', 'ex_tr', 'ex_tr_lang'];
    for (let i=0; i< vars.length; i++) {
	let v = vars[i];
	let n = find_node_xfm(uuid, ts[v]);
	if (n) {
	    if (!n.parent) {
		n.parent = v;
		n.parent_type = 'ts';
	    }
	    console.log('found node');
	    console.log(n);
	    return n;
	}
    }
}

Vue.component('elexis-dict-entry', {
    props: {
	d: Object
    },
    methods: {
	showDictModal: function(event, dsid) {
	    let component = this.$root.$refs['modal-split-ds'];
	    let dsid_input = this.$root.$refs['modal-split-ds-form-dsid'];
	    dsid_input.value = dsid;
	    component.show();
	},
	loadTransforms: function(event, dsid, is_split, uuid) {
	    this.$root.selected_ds_uuid = uuid;
	    this.$root.selected_ds = dsid;
	}
    },
    template: `
	<b-list-group-item>
	<div class="dict-entry">
	<div @click="loadTransforms($event, d.id, d.is_split, d.upload_uuid)">
	<span>{{d.id}}</span>: <span>{{d.name}}</span>
	<div v-if="this.$parent.debug_mode">{{d.upload_uuid}}</div>
	<div>Uploaded on {{d.uploaded_ts}}</div>
	<div v-if="this.$parent.debug_mode">{{d.upload_mimetype}}</div>
	<div>{{d.is_split}}</div>
	<div>{{d.entity_spec}}</div>
	</div>
	</div>
	</b-list-group-item>
	`
});

Vue.component('elexis-transform-entry', {
    props: {
	d: Object
    },
    methods: {
	editTransform: function(event, xfid) {
	    this.$root.selected_transform = xfid;
	}
    },
    template: `
	<b-list-group-item>
	<div class="transform-entry" @click="editTransform($event, d.id)">
	 <!-- <div>{{d.id}}</div>
	 <div>{{d.name}}</div>
	 <div>{{d.created_ts}}</div> -->
	 <div>{{d.name}} (<span v-if="this.$parent.debug_mode">ID = {{d.id}}, </span>{{d.created_ts}})</div>
	 <div>Split on &quot;{{d.entity_spec}}&quot;</div>
	<b-button>Edit transform</b-button><br> <br>
	<b-button @click.stop="">Export transformed</b-button>
	<b-button @click.stop="">Export transformed without namespaces</b-button>
	<b-button @click.stop="">Download exported XML</b-button>
	</div>
	</b-list-group-item>
    `
});

Vue.component('elexis-entity-list-item', {
    props: {
	d: Object
    },
    methods: {
	selectEntity: function(event, eid) {
	    this.$root.selected_entity = eid;
	}
    },
    template: `
	<b-list-group-item>
	<div class="entity-list-item" @click="selectEntity($event, d.id)">
	<!-- <div>{{d.id}}</div> -->
	<div><span>{{d.id}} </span>{{d.name.substring(0, 20)}}</div>
	</div>
	</b-list-group-item>
    `
});

Vue.component('elexis-transform-sel-spec', {
    props: {
	d: Object
    },
    template: `
	<div>
        <b-card border-variant="secondary" header="Selector" header-border-variant="secondary" align="center">

	<b-card-body>

	<div v-if="d.type === 'xpath'">
	<b-form-group>
	<b-input-group>
	<b-input-group-text slot="prepend">XPath</b-input-group-text>
	<b-form-input :id="'sel-xpath-' + d.uuid" v-model="d.expr"></b-form-input>
	</b-input-group>
	</b-form-group>
	<b-button @click="$emit('elexis-selector-prepend', d.uuid)">Prepend a selector</b-button>
	<b-button @click="$emit('elexis-selector-remove', d.uuid)">Remove selector</b-button>
	<b-button @click="$emit('elexis-selector-append', d.uuid)">Append a selector</b-button>
	<b-button @click="$emit('elexis-selector-except', d.uuid)">Subtract a selector</b-button>
	</div>

	<div v-if="d.type === 'union'">
	<elexis-transform-sel-spec v-for="(selector, index) in d.selectors" :d="selector" :key="selector.uuid" v-on="$listeners"/>
	</div>

	<div v-if="d.type === 'exclude'">
	<elexis-transform-sel-spec :d="d.left" v-on="$listeners"/>
	<div>EXCEPT</div>
	<elexis-transform-sel-spec :d="d.right" v-on="$listeners"/>
	</div>
	
    </b-card-body>
	
	</b-card>
	</div>
	`,
    created: function() {
	var vm = this.$root;
    }
});

Vue.component('elexis-transform-xf-spec', {
    props: {
	d: Object,
	noxfm: Boolean
    },
    data: function() {
	return {
	    transform_attr_options: [
		{ value: 'xao_attr', text: 'Attribute value' },
		{ value: 'xao_inner', text: 'Element inner text' },
		{ value: 'xao_subtree', text: 'Subtree text' },
		{ value: 'xao_const', text: 'Constant' },
		{ value: 'xao_none', text: '-- Select value source --', disabled: true }
	    ]
	}
    },
    template: `
	<div>
	<b-card border-variant="info" header="Transform" header-border-variant="secondary" align="center">
	<b-card-body>

	<div v-if="d.type === 'dummy'">
	<elexis-transform-sel-spec :d="d.selector" :key="d.uuid" v-on="$listeners"/>
	</div>

	<div v-else-if="d.type === 'simple'">

	<elexis-transform-sel-spec :d="d.selector" :key="d.uuid" v-on="$listeners"/>
	
	<b-card-body>
	<b-input-group>
	<b-input-group-text slot="prepend">Value</b-input-group-text>
	<b-form-select :options="transform_attr_options" v-model="d.attr_type"></b-form-select>
	<b-form-input type="text" v-if="d.attr_type === 'xao_attr'" v-model="d.attr">Attribute name</b-form-input>
	<b-form-input type="text" v-if="d.attr_type === 'xao_const'" v-model="d.const">Fixed value</b-form-input>
	<b-form-input type="text" readonly v-if="!(d.attr_type === 'xao_const' || d.attr_type === 'xao_attr')"></b-form-input>
	</b-input-group>

	<b-input-group>
	<b-input-group-text slot="prepend">Regular expression</b-input-group-text>
	<b-form-input type="text" v-model="d.rex"></b-form-input>
	</b-input-group>
	
	<b-input-group>
	<b-input-group-text slot="prepend">Regular expression group</b-input-group-text>
	<b-form-input type="text" v-model="d.rex_group" :readonly="!(d.rex && d.rex.length > 0)"></b-form-input>
	</b-input-group>
	</b-card-body>

	<div>
	<b-button @click="$emit('elexis-transform-prepend', d.uuid)">Prepend a transform</b-button>
	<b-button @click="$emit('elexis-transform-append', d.uuid)">Add a transform</b-button>
	<b-button @click="$emit('elexis-transform-remove', d.uuid)">Remove transform</b-button>
	</div>

	</div>

	<div v-else-if="d.type === 'union'">
	<elexis-transform-xf-spec v-for="(transformer, index) in d.transformers" :d="transformer" :key="transformer.uuid" v-on="$listeners"/>
	</div>

    </b-card-body>
	</b-card>

	</div>
	`,
    created: function() {
	var vm = this.$root;
    }
});

Vue.component('elexis-transform-var-item', {
    props: {
	d: Object,
	var_name: String
    },
    methods: {
    },
    computed: {
	naked_transform: function() {
	    return this.var_name == 'entry' || this.var_name == 'sense';
	}
    },
    data: function() {
	return {
	    vars_to_string: {
		'def': 'Definition',
		'entry': 'Entry',
		'entry_lang': 'Entry language',
		'sense': 'Sense',
		'hw': 'Headword',
		'hw_tr': 'Headword translation',
		'hw_tr_lang': 'Headword translation language',
		'ex': 'Example',
		'ex_tr': 'Example translation',
		'ex_tr_lang': 'Example translation language',
	    }
	}
    },
    template: `
    <b-list-group-item>
	<b-card no-body>
	<b-card-header header-tag="header" class="p-1" role="tab">
	<b-button block href="#" v-b-toggle="'transforms-accordion-' + var_name" variant="info">{{vars_to_string[var_name]}}</b-button>
	</b-card-header>
	<b-collapse :id="'transforms-accordion-' + var_name" :visible="var_name=='entry'" :accordion="'transforms-accordion-' + var_name" role="tabpanel">
	<b-card-body>
	<b-card-text>
	<elexis-transform-xf-spec v-bind:d="d" :key="d.uuid" :noxfm="naked_transform" v-on="$listeners"/>
	</b-card-text>
	</b-card-body>
	</b-collapse>
	</b-card>
    </b-list-group-item>
    `
});

const vm = new Vue({
    el: '#app',
    data: {
	debug_mode: false,
	selected_transform: false,
	selected_ds: null,
	selected_ds_uuid: null,
	dict_list: [],
	transform_list: [],
	entity_list_waiting: false,
	entity_list: [],
	selected_entity: null,
	search_entity: '',
	transform_spec: [],
	transform_strip_ns: false,
	transform_modified: false,
	display_internal_transform: true,
	dropzoneOptions: {
            url: '/api/dataset/upload',
            maxFilesize: 999,
	    chunkSize: 200000,
	    chunking: true,
	    forceChunking: true,
	}	
    },
    computed: {
	current_transform: function() {
	    if (this.display_internal_transform) {
		return this.transform_spec;
	    } else {
		return transform_js_to_db(this.transform_spec);
	    }
	},
	filtered_entity_list: function() {
	    let se = this.search_entity;
	    if (se == '') {
/*		if (this.debug_mode) {
		    let arr = [];
		    for (let i=0; i < 50; i++) {
			arr.push(this.entity_list[0]);
		    }
		    return arr;
		}
*/
		return this.entity_list;
	    } else {
		return this.entity_list.filter(function (o) {
		    return o.name.toLowerCase().indexOf(se) !== -1;
		});
	    }
	}
    },
    watch: {
	transform_spec: {
	    handler: function(newVal, oldVal) {
		if ((newVal == null) || (Array.isArray(newVal) && newVal.length == 0)) {
		    vm.transform_modified = false;
		    return;
		}
		if (Array.isArray(oldVal) && oldVal.length == 0) {
		    return;
		}
		if (!vm.transform_modified) {
		    vm.transform_modified = true;
		    //console.log("xfm mod");
		}
	    },
	    deep: true
	},
//	transform_modified: function(newVal, oldVal) {
//	    console.log("xfm mod", oldVal, newVal);
//	},
	selected_ds: function() {
	    this.transform_list_refresh();
	},
	selected_transform: function() {
	    this.populate_transform();
	},
	selected_entity: function() {
	    this.run_transform_entity();
	},
	transform_strip_ns: function() {
	    this.run_transform_entity();
	},
    },
    methods: {
	unload_hanler: function(event) {
//	    event.preventDefault();
//	    event.returnValue = '';
	    console.log("unloading");
	},
	exit_xfm_view: function() {
	    vm.selected_entity = null;
	    vm.selected_transform = null;
	    vm.transform_spec = [];
	},
	dm_xfm_prepend: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('xp');

	    // n: { node: xfm, parent: xfm | t_s[name] }
	    if (n.parent_type === 'ts') {
		let nn = new_xfm();
		let nu = new_xfm();
		nu.type = 'union';
		nu.transformers = [nn, n.node];
		vm.transform_spec[n.parent] = nu;
	    } else if (n.parent_type === 'xfm-u') {
		//n.parent.transformers.unshift(new_xfm());
		n.parent.transformers.splice(n.parent_idx, 0, new_xfm());
	    }
	},
	dm_xfm_append: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('xa');

	    if (n.parent_type === 'ts') {
		let nn = new_xfm();
		let nu = new_xfm();
		nu.type = 'union';
		nu.transformers = [n.node, nn];
		vm.transform_spec[n.parent] = nu;
	    } else if (n.parent_type === 'xfm-u') {
		//n.parent.transformers.push(new_xfm());
		n.parent.transformers.splice(n.parent_idx+1, 0, new_xfm());
	    }
	},
	dm_xfm_remove: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('xr');
	    if (n.parent_type === 'xfm-u') {
		n.parent.transformers.splice(n.parent_idx, 1);
		if (n.parent.transformers.length === 1) {
		    let only_remaining_child = n.parent.transformers[0];
		    let p = find_node(n.parent.uuid, vm.transform_spec);
		    // assert p.parent_type == 'ts'
		    console.log(p.parent_type);
		    vm.transform_spec[p.parent] = only_remaining_child;
		}
	    }
	},
	dm_sel_prepend: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('sp');

	    if (n.parent.supertype === 'selector') {
		if (n.parent.type === 'exclude') {
		    let nn = new_sel();
		    let uu = new_sel();
		    uu.type = 'union';
		    uu.selectors = [nn, n.node];

		    if (n === parent.left) {
			n.parent.left = uu;
		    } else if (n === parent.right) {
			n.parent.right = uu;
		    }
		} else if (n.parent.type === 'union') {
		    //n.parent.selectors.unshift(new_sel());
		    n.parent.selectors.splice(n.parent_idx, 0, new_sel());
		}
	    } else if (n.parent.supertype == 'transformer') {
		let nn = new_sel();
		let uu = new_sel();
		uu.type = 'union';
		uu.selectors = [nn, n.node];
		n.parent.selector = uu;
	    }
	},
	dm_sel_append: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('sa');

	    if (n.parent.supertype === 'selector') {
		if (n.parent.type === 'exclude') {
		    let nn = new_sel();
		    let uu = new_sel();
		    uu.type = 'union';
		    uu.selectors = [n.node, nn];

		    if (n.node === parent.left) {
			n.parent.left = uu;
		    } else if (n.node === parent.right) {
			n.parent.right = uu;
		    }
		} else if (n.parent.type === 'union') {
		    //n.parent.selectors.push(new_sel());
		    n.parent.selectors.splice(n.parent_idx+1, 0, new_sel());
		}
	    } else if (n.parent.supertype == 'transformer') {
		let nn = new_sel();
		let uu = new_sel();
		uu.type = 'union';
		uu.selectors = [n.node, nn];
		n.parent.selector = uu;
	    }
	},
	dm_sel_except: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('se');
	    let nn = new_sel();
	    nn.type = 'exclude';
	    nn.left = n.node;
	    nn.right = new_sel();

	    // could be in transformer.selector, selector.union, selector.except.l, selector.except.r
	    if (n.parent.supertype === 'transformer') {
		n.parent.selector = nn;
	    } else if (n.parent.supertype === 'selector') {
		if (n.parent.type === 'exclude') {
		    if (n.node === n.parent.left) {
			n.parent.left = nn;
		    } else if (n.node === n.parent.right) {
			n.parent.right = nn;
		    }
		} else if (n.parent.type === 'union') {
		    n.parent.selectors.splice(n.parent_idx, 1, nn);
		}
	    }
	},
	// hax
	replace_node: function(uuid, r) {
	    let n = find_node(uuid, vm.transform_spec);
	    if (n.parent_type === 'ts') { // special case. f***. change xfm functions to use n.parent.supertype, return ts node as parent, var name as index
		// doesn't get called from selector manipulation anyway.
		vm.transform_spec[n.parent] = r;
	    } else if (n.parent.supertype === 'transformer') {
		if (n.parent.type === 'simple' || n.parent.type === 'dummy') {
		    // n.supertype better be a selector ....
		    if (!(n.node.supertype === 'selector')) {
			console.log("wtf");
		    }
		    n.parent.selector = r;
		} else if (n.parent.type === 'union') {
		    console.log("xfm replace not implemented yet");
		}
	    } else if (n.parent.supertype === 'selector') {
		if (n.parent.type === 'exclude') {
		    if (n.node === n.parent.left) n.parent.left = r;
		    if (n.node === n.parent.right) n.parent.right = r;
		} else if (n.parent.type === 'union') {
		    n.parent.selectors.splice(n.parent_idx, 1);
		    if (n.parent.selectors.length > 1) console.log("why did we start with an union of len 1???");
		}
	    }
	},
	dm_sel_remove: function(uuid) {
	    let n = find_node(uuid, vm.transform_spec);
	    console.log('sr');

	    if (n.parent.supertype === 'transformer') {
		// nopez. can't remove.
		console.log("won't remove top level selector");
	    } else if (n.parent.supertype === 'selector') {
		if (n.parent.type === 'exclude') {
		    if (n.node === n.parent.left) {
			console.log('wiping parent');
			this.dm_sel_remove(n.parent.uuid);  // wipe entire parent
		    } else if (n.node === n.parent.right) {
			// convert parent to simple using n.parent.left
			console.log('downgrading exclude parent');
			// replace parent with n.parent.left [in the grandparent]
			this.replace_node(n.parent.uuid, n.parent.left);
		    }
		} else if (n.parent.type === 'union') {
		    console.log('removing from union');
		    n.parent.selectors.splice(n.parent_idx, 1);
		    if (n.parent.selectors.length === 1) {
			// !!!!!!!!
			console.log('downgrading union parent');
			// replace parent with n.parent.selectors[0] [in the grandparent]
			this.replace_node(n.parent.uuid, n.parent.selectors[0]);
		    }
		}
	    }
	},
	run_transform_entity: function() {
		console.log(this.selected_entity)
	    if (!this.selected_entity) return;
	    console.log('Sm pride')
	    let xfid = this.selected_transform;
	    let entity_id = this.selected_entity;
	    axios.get(
		`/api/transform/${xfid}/apply/${entity_id}`,
		{ params: { strip_ns: this.transform_strip_ns, Authorization: this.$root.auth_token}}
	    ).then((response) => {
		//console.log(response);
		this.$refs['xfin'].value = response.data.entity_xml;
		this.$refs['xfout'].value = response.data.output;
	    });
	},
	upload_transform: function() {
	    axios.post(`/api/transform/${this.selected_transform}`, {
		'xfspec': transform_js_to_db(this.transform_spec)
	    },
        {headers: {Authorization: this.$root.auth_token,}}
	    ).then((response) => {
		this.transform_modified = false;
		this.run_transform_entity();
	    });
	},
	populate_transform: function() {
	    if (!this.selected_transform) return;
	    this.entity_list_waiting = true;
	    axios.get(`/api/transform/${this.selected_transform}`,
        {headers: {Authorization: this.$root.auth_token,}
	    }).then((response) => {
		this.entity_list_waiting = false;
		let t = vm;
		t.entity_list.splice(0);
		response.data['entities'].forEach((item, index) => {
		    t.entity_list.push(item);
		});
		this.transform_spec = transform_db_to_js(response.data.transform.transform);
		this.transform_modified = false;
	    });
	},
	okTransformModal: function(event) {
	    let name = this.$root.$refs['modal-create-transform-form-xfname'].value;
	    let xpath = this.$root.$refs['modal-create-transform-form-entryspec'].value;
	    let dsuuid = this.$root.selected_ds_uuid;
	    let dsid = this.$root.selected_ds;
	    axios.post('/api/transform/new', {
		'dsuuid': dsuuid,
		'dsid': dsid,
		'xfname': name,
		'entry_spec': xpath
	    },
        {headers: {Authorization: this.$root.auth_token,}}
	    ).then((request) => {
		this.transform_list_refresh();
	    });
	},
	dictuploadadd: function(file) {
	    console.log("added");
	},
	dictuploadok: function(file) {
	    console.log("upload");
	    this.$refs.dictdropzone.removeFile(file);
	    this.dict_refresh();
	},
	dict_refresh: function() {
	    axios.get("/api/dataset/list", 
	    {headers: {Authorization: this.$root.auth_token,}
	    }).then((response) => {
		    let t = vm;
		    t.dict_list.splice(0);
		    response.data.forEach((item,index) => {
			t.dict_list.push(item);
			}
		    );
		});
	},
	transform_list_refresh: function() {
	    let ds = this.selected_ds;
	    if (!ds) return;
	    axios.get(`/api/transform/list/${ds}`,
        {headers: {Authorization: this.$root.auth_token,}
	    }).then((response) => {
		let t = vm;
		t.transform_list.splice(0);
		response.data.forEach((item,index) => {
		    t.transform_list.push(item);
		});
	    });
	},
    },
    components: {
	vueDropzone: vue2Dropzone
    },
    created: function() {
		var vm = this;
		let uri = window.location.search.substring(1); 
	    let params = new URLSearchParams(uri);
	    this.$root.auth_token = JSON.parse(params.get("response"))["auth_token"];
	    console.log(this.$refs.dictdropzone)
	    this.dict_refresh();

	    this.dropzoneOptions.headers = {Authorization: this.$root.auth_token,}
	    //this.$refs.dictdropzone.setOption('url', `http://your-url.com/`);
	    console.log(this.data)
	    
	    document.addEventListener('beforeunload', this.unload_handler);
    }
});


