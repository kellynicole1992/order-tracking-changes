from lib import clusters
from functools import cmp_to_key
from lib.objects_to_sheet import ObjectsToSheet
from typing import Any, TypeVar

_T = TypeVar('_T')


def total_diff(cluster) -> Any:
  if cluster.manual_override:
    return 0
  return cluster.tracked_cost + cluster.adjustment - cluster.expected_cost


def compare_ship_dates(cluster_one, cluster_two):
  if cluster_one.last_ship_date < cluster_two.last_ship_date:
    return -1
  elif cluster_one.last_ship_date == cluster_two.last_ship_date:
    return 0
  else:
    return 0


def compare(cluster_one, cluster_two) -> int:
  if cluster_two.verified: 
    return -1
  elif cluster_one.verified and  cluster_two.below_cost:  
    return 0
  elif not cluster_one.verified and  cluster_two.below_cost:  
    return -1 
  else: 
    if total_diff(cluster_one) < total_diff(cluster_two): 
      return 1  
    else:   
      return 0

def has_formatting(service, base_sheet_id, ranges):
  response = service.spreadsheets().get(spreadsheetId=base_sheet_id, ranges=ranges).execute()
  return "conditionalFormats" in str(response)


def clear_protected_ranges(service, base_sheet_id, ranges):
  response = service.spreadsheets().get(spreadsheetId=base_sheet_id, ranges=ranges).execute()
  sheet = response['sheets'][0]
  if "protectedRanges" in sheet:
    ids = [pr['protectedRangeId'] for pr in sheet['protectedRanges']]
    for id in ids:
      body = {"requests": [{"deleteProtectedRange": {"protectedRangeId": id}}]}
      service.spreadsheets().batchUpdate(spreadsheetId=base_sheet_id, body=body).execute()


def clear_formatting(service, base_sheet_id, tab_id, ranges):
  while has_formatting(service, base_sheet_id, ranges):
    body = {"requests": [{"deleteConditionalFormatRule": {"sheetId": int(tab_id), "index": 0}}]}
    service.spreadsheets().batchUpdate(spreadsheetId=base_sheet_id, body=body).execute()


def get_conditional_formatting_body(service, base_sheet_id, tab_title, num_objects):
  response = service.spreadsheets().get(spreadsheetId=base_sheet_id, ranges=[tab_title]).execute()
  tab = [sheet for sheet in response['sheets'] if sheet['properties']['title'] == tab_title][0]
  tab_id = tab['properties']['sheetId']

  ranges = [tab_title]
  clear_formatting(service, base_sheet_id, tab_id, ranges)
  clear_protected_ranges(service, base_sheet_id, ranges)

  header_protected_range = {
      "sheetId": int(tab_id),
      "startRowIndex": 0,
      "endRowIndex": 1,
      "startColumnIndex": 0,
      "endColumnIndex": 50,
  }
  po_protected_range = {
      "sheetId": int(tab_id),
      "startRowIndex": 1,
      "endRowIndex": num_objects + 1,
      "startColumnIndex": 8,
      "endColumnIndex": 9,
  }
  checkbox_range = {
      "sheetId": int(tab_id),
      "startRowIndex": 1,
      "endRowIndex": num_objects + 1,
      "startColumnIndex": 11,
      "endColumnIndex": 12
  }
  checkbox_range_2 = {  
      "sheetId": int(tab_id), 
      "startRowIndex": 1, 
      "endRowIndex": num_objects + 1, 
      "startColumnIndex": 16, 
      "endColumnIndex": 17  
  } 
  checkbox_range_3 = {  
      "sheetId": int(tab_id), 
      "startRowIndex": 1, 
      "endRowIndex": num_objects + 1, 
      "startColumnIndex": 13, 
      "endColumnIndex": 14  
  }
  total_diff_range = {
      "sheetId": int(tab_id),
      "startRowIndex": 1,
      "endRowIndex": num_objects + 1,
      "startColumnIndex": 12,
      "endColumnIndex": 13
  }
  requests = [
      # freeze the header in place
      {
          "updateSheetProperties": {
              "properties": {
                  "sheetId": int(tab_id),
                  "gridProperties": {
                      "frozenRowCount": 1
                  }
              },
              "fields": "gridProperties.frozenRowCount"
          }
      },
      {
          "setDataValidation": {
              "range": checkbox_range,
              "rule": {
                  "condition": {
                      'type': 'BOOLEAN'
                  }
              }
          }
      },
      { 
            "setDataValidation": {  
                "range": checkbox_range_2,  
                "rule": { 
                    "condition": {  
                        'type': 'BOOLEAN' 
                    } 
                } 
            } 
        },  
        { 
            "setDataValidation": {  
                "range": checkbox_range_3,  
                "rule": { 
                    "condition": {  
                        'type': 'BOOLEAN' 
                    } 
                } 
            } 
        },
      {
          "addProtectedRange": {
              "protectedRange": {
                  "range": header_protected_range,
                  "description": "Do not edit the header titles!",
                  "warningOnly": True
              }
          }
      },
      {
          "addProtectedRange": {
              "protectedRange": {
                  "range": po_protected_range,
                  "description": "Be careful when editing purchase orders!",
                  "warningOnly": True
              }
          }
      },
      {
          # Green if the box is checked or the prices are equal
          "addConditionalFormatRule": {
              "index": 0,
              "rule": {
                  "ranges": [total_diff_range],
                  "booleanRule": {
                      "condition": {
                          "type": "CUSTOM_FORMULA",
                          "values": [{
                              'userEnteredValue': '=OR((K2:K)+(E2:E)=D2:D, L2:L=TRUE)'
                          }]
                      },
                      "format": {
                          'backgroundColor': {
                              'red': 0.7176471,
                              'green': 0.88235295,
                              'blue': 0.8039216
                          }
                      }
                  }
              }
          }
      },
      {
                # Blue if within 5% amount billed
          "addConditionalFormatRule": {
              "index": 1,
              "rule": {
                  "ranges": [total_diff_range],
                  "booleanRule": {
                      "condition": {
                          "type": "CUSTOM_FORMULA",
                          "values": [{
                              'userEnteredValue': '=AND(M2:M<=D2:D*0.05, M2:M>=0)'
                          }]
                      },
                      "format": {
                          'backgroundColor': {
                              'red': 0.596,
                              'green': 0.71,
                              'blue': 0.816
                          }
                      }
                  }
              }
          }
      },
      {
          # Yellow if overcompensated
          "addConditionalFormatRule": {
              "index": 2,
              "rule": {
                  "ranges": [total_diff_range],
                  "booleanRule": {
                      "condition": {
                          "type": "CUSTOM_FORMULA",
                          "values": [{
                              'userEnteredValue': '=(K2:K)+(E2:E)>D2:D'
                          }]
                      },
                      "format": {
                          'backgroundColor': {
                              'red': 0.9882353,
                              'green': 0.9098039,
                              'blue': 0.69803923
                          }
                      }
                  }
              }
          }
      },
      {
          # Red if undercompensated
          "addConditionalFormatRule": {
              "index": 3,
              "rule": {
                  "ranges": [total_diff_range],
                  "booleanRule": {
                      "condition": {
                          "type": "CUSTOM_FORMULA",
                          "values": [{
                              'userEnteredValue': '=(K2:K)+(E2:E)<D2:D'
                          }]
                      },
                      "format": {
                          'backgroundColor': {
                              'red': 0.95686275,
                              'green': 0.78039217,
                              'blue': 0.7647059
                          }
                      }
                  }
              }
          }
      }
  ]
  return {"requests": requests}


class ReconciliationUploader:

  def __init__(self, config) -> None:
    self.config = config
    self.objects_to_sheet = ObjectsToSheet()

  def override_pos_and_costs(self, all_clusters):
    print("Filling manual PO adjustments")
    base_sheet_id = self.config['reconciliation']['baseSpreadsheetId']
    downloaded_clusters = self.objects_to_sheet.download_from_sheet(clusters.from_row,
                                                                    base_sheet_id,
                                                                    "Reconciliation v2")

    for cluster in all_clusters:
      candidate_downloads = self.find_candidate_downloads(cluster, downloaded_clusters)
      pos = set()
      non_reimbursed_trackings = set()
      total_tracked_cost = 0.0
      for candidate in candidate_downloads:
        pos.update(candidate.purchase_orders)
        non_reimbursed_trackings.update(candidate.non_reimbursed_trackings)
        total_tracked_cost += candidate.tracked_cost
      cluster.purchase_orders = pos
      cluster.non_reimbursed_trackings = non_reimbursed_trackings
      cluster.tracked_cost = total_tracked_cost

  def download_upload_clusters_new(self, all_clusters) -> None:
    base_sheet_id = self.config['reconciliation']['baseSpreadsheetId']
    self.fill_adjustments(all_clusters, base_sheet_id, "Reconciliation v2")

    all_clusters.sort(key=cmp_to_key(compare))
    print("Uploading new reconciliation to sheet")
    self.objects_to_sheet.upload_to_sheet(all_clusters, base_sheet_id, "Reconciliation v2",
                                          get_conditional_formatting_body)

  def fill_adjustments(self, all_clusters, base_sheet_id, tab_title) -> None:
    print("Filling in cost adjustments if applicable")
    downloaded_clusters = self.objects_to_sheet.download_from_sheet(clusters.from_row,
                                                                    base_sheet_id, tab_title)

    for cluster in all_clusters:
      candidate_downloads = self.find_candidate_downloads(cluster, downloaded_clusters)
      cluster.adjustment = sum([candidate.adjustment for candidate in candidate_downloads])
      cluster.notes = "; ".join(
          [candidate.notes for candidate in candidate_downloads if candidate.notes.strip()])
      # Import the manual override boolean from the sheet's checkbox ONLY if:
      # (a) no clusters have been merged in since the last sheet export and
      # (b) there haven't been any new order IDs or tracking #s added to the
      #     cluster since the last export.
      if len(candidate_downloads) == 1:
        sheet_cluster = candidate_downloads[0]
        if (sheet_cluster.trackings == cluster.trackings and
            sheet_cluster.orders == cluster.orders):
          cluster.manual_override = sheet_cluster.manual_override
          cluster.verified = sheet_cluster.verified
          cluster.below_cost = sheet_cluster.below_cost

  def find_candidate_downloads(self, cluster, downloaded_clusters) -> list:
    result = []
    for downloaded_cluster in downloaded_clusters:
      if downloaded_cluster.trackings.intersection(cluster.trackings):
        result.append(downloaded_cluster)
    return result
