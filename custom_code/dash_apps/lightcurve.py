import dash_core_components as dcc
import dash_html_components as html
import plotly.graph_objs as go
from dash.dependencies import Input, Output, State
import json
from django_plotly_dash import DjangoDash
from tom_dataproducts.models import ReducedDatum
from custom_code.models import ReducedDatumExtra

app = DjangoDash(name='Lightcurve')
telescopes = ['LCO']
reducer_groups = []
papers_used_in = []
app.layout = html.Div([
    dcc.Graph(
        id='lightcurve-plot'
    ),
    dcc.Input(
        id='target_id',
        type='hidden',
        value=0
    ),
    dcc.Input(
        id='plot-width',
        type='hidden',
        value=0
    ),
    dcc.Input(
        id='plot-height',
        type='hidden',
        value=0
    ),
    html.H3('Instrument'),
    dcc.Checklist(
        id='telescopes-checklist',
        options=[{'label': k, 'value': k} for k in telescopes],
        value=telescopes
    ),
    html.Hr(),
    html.H3('Difference Imaging'),
    dcc.RadioItems(
        id='subtracted-radio',
        options=[{'label': 'Unsubtracted', 'value': 'Unsubtracted'},
                 {'label': 'Subtracted', 'value': 'Subtracted'}
        ],
        value='Unsubtracted',
        style={'display': 'none'}
    ),
    html.Div(
        id='subtracted-extras',
        children=[
            html.H4('Subtraction Algorithm'),
            dcc.Checklist(
                id='algorithm-checklist',
                options=[{'label': 'Hotpants', 'value': 'Hotpants'},
                         {'label': 'PyZOGY', 'value': 'PyZOGY'}
                ],
                value=['Hotpants', 'PyZOGY']
            ),
            html.H4('Template Source'),
            dcc.Checklist(
                id='template-checklist',
                options=[{'label': 'LCO', 'value': 'LCO'},
                         {'label': 'SDSS', 'value': 'SDSS'}
                ],
                value=['LCO', 'SDSS']
            )
        ],
        style={'display': 'none'}
    ),
    html.Hr(),
    html.H3('Photometry Type'),
    dcc.Checklist(
        id='photometry-type-checklist',
        options=[{'label': 'PSF', 'value': 'PSF'},
                 {'label': 'Aperture', 'value': 'Aperture'}
        ],
        value=['PSF', 'Aperture']
    ),
    html.Hr(),
    html.H3('Reduction Type'),
    dcc.Checklist(
        id='reduction-type-checklist',
        options=[{'label': 'Automatic', 'value': ''},
                 {'label': 'Manual', 'value': 'manual'}
        ],
        value=['', 'manual']
    ),
    dcc.Checklist(
        id='final-reduction-checklist',
        options=[{'label': 'Final Reduction?', 'value': 'Final'}],
        value=''
    ),
    html.Hr(),
    html.H3('Data Used In'),
    dcc.Dropdown(
        id='papers-dropdown',
        options=[{'label': '', 'value': ''}],
        value=None
    ),
    html.Hr(),
    html.H3('Data from Group'),
    dcc.Checklist(
        id='reducer-group-checklist',
        options=[{'label': 'LCO', 'value': ''}],
        value=['']
    ),
    html.Hr(),
    html.Div(
        id='display-selected-values')
])

#Only show manually reduced data if subtracted is selected
@app.callback(
        Output('reduction-type-checklist', 'value'),
        [Input('subtracted-radio', 'value'),
         State('reduction-type-checklist', 'value')])
def update_reduction_type(selected_subtraction, old_reduction_type):
    if selected_subtraction == 'Subtracted':
        return ['manual']
    return old_reduction_type

#Unselect final reduction if automatically reduced data is selected
@app.callback(
        Output('final-reduction-checklist', 'value'),
        [Input('reduction-type-checklist', 'value'),
         State('final-reduction-checklist', 'value')])
def update_final_reduction(selected_reduction, old_final_value):
    if '' in selected_reduction:
        return ''
    return old_final_value

#Select unsubtracted data if automatic subtraction is selected
@app.callback(
        Output('subtracted-radio', 'value'),
        [Input('reduction-type-checklist', 'value'),
         State('subtracted-radio', 'value')])
def update_subtracted_type(selected_reduction, old_subtracted_type):
    if '' in selected_reduction:
        return 'Unsubtracted'
    return old_subtracted_type

#Hide subtracted choices if LCO telescope is not selected
@app.callback(
        Output('subtracted-radio', 'style'),
        [Input('telescopes-checklist', 'value')])
def update_subtracted_style(selected_telescope):
    if 'LCO' in selected_telescope:
        return {}
    else:
        return {'display': 'none'}

#Only show algorithm choices if subtracted data is selected
@app.callback(
        Output('subtracted-extras', 'style'),
        [Input('subtracted-radio', 'value')])
def update_algorith_style(selected_subtraction):
    if selected_subtraction == 'Subtracted':
        return {}
    else:
        return {'display': 'none'}

#Automatically select both subtraction algorithms when subtracted data is selected
@app.callback(
        Output('algorithm-checklist', 'value'),
        [Input('subtracted-radio', 'value')])
def update_algorithm_value(selected_subtraction):
    return ['Hotpants', 'PyZOGY']

#Automatically select both template choices when subtracted data is selected
@app.callback(
        Output('template-checklist', 'value'),
        [Input('subtracted-radio', 'value')])
def update_template_value(selected_subtraction):
    return ['LCO', 'SDSS']

@app.callback(
        Output('lightcurve-plot', 'figure'),
        [Input('telescopes-checklist', 'value'),
         Input('subtracted-radio', 'value'),
         Input('algorithm-checklist', 'value'),
         Input('template-checklist', 'value'),
         Input('photometry-type-checklist', 'value'),
         Input('reduction-type-checklist', 'value'),
         Input('final-reduction-checklist', 'value'),
         Input('papers-dropdown', 'value'),
         Input('reducer-group-checklist', 'value'),
         Input('target_id', 'value'),
         Input('plot-width', 'value'),
         Input('plot-height', 'value')])
def update_graph(selected_telescope, subtracted_value, selected_algorithm, selected_template, selected_photometry_type, reduction_type, final_reduction_value, selected_paper, selected_groups, value, width, height):
    def get_color(filter_name):
        filter_translate = {'U': 'U', 'B': 'B', 'V': 'V',
            'g': 'g', 'gp': 'g', 'r': 'r', 'rp': 'r', 'i': 'i', 'ip': 'i',
            'g_ZTF': 'g_ZTF', 'r_ZTF': 'r_ZTF', 'i_ZTF': 'i_ZTF', 'UVW2': 'UVW2', 'UVM2': 'UVM2',
            'UVW1': 'UVW1'}
        colors = {'U': 'rgb(59,0,113)',
            'B': 'rgb(0,87,255)',
            'V': 'rgb(120,255,0)',
            'g': 'rgb(0,204,255)',
            'r': 'rgb(255,124,0)',
            'i': 'rgb(144,0,43)',
            'g_ZTF': 'rgb(0,204,255)',
            'r_ZTF': 'rgb(255,124,0)',
            'i_ZTF': 'rgb(144,0,43)',
            'UVW2': '#FE0683',
            'UVM2': '#BF01BC',
            'UVW1': '#8B06FF',
            'other': 'rgb(0,0,0)'}
        try: color = colors[filter_translate[filter_name]]
        except: color = colors['other']
        return color
    
    target_id = value
    photometry_data = {}
    subtracted_photometry_data = {}
    datumextras = ReducedDatumExtra.objects.filter(target_id=target_id, key='upload_extras', data_type='photometry')
    
    datums = []
    
    ### Check if this is a final reduction or not
    if 'Final' in final_reduction_value:
        final_reduction = True
    else:
        final_reduction = False

    ### Get the data for the selected telescope
    if not selected_telescope:
        datums.append(ReducedDatum.objects.filter(target_id=target_id, data_type='photometry'))
    
    else:
        for de in datumextras:
            de_value = de.value

            ### Test that this dataproduct meets the chosen criteria:
            if all([de_value.get('instrument', '') in selected_telescope,
                    de_value.get('photometry_type', '') in selected_photometry_type,
                    (not final_reduction or de_value.get('final_reduction', '')==final_reduction),
                    de_value.get('reducer_group', '') in selected_groups,
                    (not selected_paper or de_value.get('used_in', '')==selected_paper)]):
                dp_id = de_value.get('data_product_id', '')
                datums.append(ReducedDatum.objects.filter(target_id=target_id, data_type='photometry', data_product_id=dp_id))
        
        ### Finally, get the data that was automatically uploaded from snex1 db
        if 'LCO' in selected_telescope and not final_reduction:
            datums.append(ReducedDatum.objects.filter(target_id=target_id, data_type='photometry', data_product_id__isnull=True))
    
    ### Plot the data
    if not datums:
        return 'No photometry yet'
    for data in datums:
        for rd in data:
            value = rd.value
            if not value:
                continue

            ### Get subtracted or unsubtracted data
            if value.get('background_subtracted', '') == True:
                if value.get('subtraction_algorithm', '') in selected_algorithm and value.get('template_source', '') in selected_template and 'manual' in reduction_type:
                    subtracted_photometry_data.setdefault(value.get('filter', ''), {})
                    subtracted_photometry_data[value.get('filter', '')].setdefault('time', []).append(rd.timestamp)
                    subtracted_photometry_data[value.get('filter', '')].setdefault('magnitude', []).append(value.get('magnitude',None))
                    subtracted_photometry_data[value.get('filter', '')].setdefault('error', []).append(value.get('error', None))
            elif value.get('reduction_type', '') in reduction_type:
                photometry_data.setdefault(value.get('filter', ''), {})
                photometry_data[value.get('filter', '')].setdefault('time', []).append(rd.timestamp)
                photometry_data[value.get('filter', '')].setdefault('magnitude', []).append(value.get('magnitude',None))
                photometry_data[value.get('filter', '')].setdefault('error', []).append(value.get('error', None))

    if subtracted_value == 'Unsubtracted':
        selected_photometry = photometry_data
    elif subtracted_value == 'Subtracted':
        selected_photometry = subtracted_photometry_data
    plot_data = [
        go.Scatter(
            x=filter_values['time'],
            y=filter_values['magnitude'], mode='markers',
            marker=dict(color=get_color(filter_name)),
            name=filter_name,
            error_y=dict(
                type='data',
                array=filter_values['error'],
                visible=True,
                color=get_color(filter_name)
            )
        ) for filter_name, filter_values in selected_photometry.items()]

    graph_data = {'data': plot_data}

    layout = go.Layout(
        xaxis=dict(gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        yaxis=dict(autorange='reversed',gridcolor='#D3D3D3',showline=True,linecolor='#D3D3D3',mirror=True),
        margin=dict(l=30, r=40, b=30, t=40),
        width=width,
        height=height,
        hovermode='closest',
        plot_bgcolor='white'
    )

    graph_data['layout'] = layout

    return graph_data
