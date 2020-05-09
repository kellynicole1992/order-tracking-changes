#!/usr/bin/env python3

import argparse
import lib.donations
from lib import clusters
import sys
import time
from tqdm import tqdm
import yaml
from lib.cancelled_items_retriever import CancelledItemsRetriever
from lib.order_info import OrderInfo, OrderInfoRetriever
from lib.group_site_manager import GroupSiteManager
from lib.driver_creator import DriverCreator
from lib.reconciliation_uploader import ReconciliationUploader
from lib.tracking_output import TrackingOutput
from lib.tracking_uploader import TrackingUploader

CONFIG_FILE = "config.yml"


def fill_costs(all_clusters, config):
  print("Filling costs")
  order_info_retriever = OrderInfoRetriever(config)
  for cluster in all_clusters:
    cluster.expected_cost = 0.0
    for order_id in cluster.orders:
      try:
        order_info = order_info_retriever.get_order_info(order_id)
      except Exception as e:
        print(
            f"Exception when getting order info for {order_id}. Please check the oldest email associated with that order. Skipping..."
        )
        print(str(e))
        continue
      cluster.expected_cost += order_info.cost


def fill_email_ids(all_clusters, config):
  order_info_retriever = OrderInfoRetriever(config)
  total_orders = sum([len(cluster.orders) for cluster in all_clusters])
  with tqdm(
      desc='Fetching order costs', unit='order', total=total_orders) as pbar:
    for cluster in all_clusters:
      cluster.expected_cost = 0.0
      cluster.email_ids = set()
      for order_id in cluster.orders:
        try:
          order_info = order_info_retriever.get_order_info(order_id)
          # Only add the email ID if it's present; don't add Nones!
          if order_info.email_id:
            cluster.email_ids.add(order_info.email_id)
          cluster.expected_cost += order_info.cost
        except Exception as e:
          tqdm.write(
              f"Exception when getting order info for {order_id}. Please check the oldest email associated with that order. Skipping..."
          )
          tqdm.write(str(e))
        pbar.update()


def get_new_tracking_pos_costs_maps(config, group_site_manager, args):
  print("Loading tracked costs. This will take several minutes.")
  if args.groups:
    print("Only reconciling groups %s" % ",".join(args.groups))
    groups = args.groups
  else:
    groups = config['groups'].keys()

  trackings_to_costs_map = {}
  po_to_cost_map = {}
  for group in groups:
    group_trackings_to_po, group_po_to_cost = group_site_manager.get_new_tracking_pos_costs_maps_with_retry(
        group)
    trackings_to_costs_map.update(group_trackings_to_po)
    po_to_cost_map.update(group_po_to_cost)
    #print(f"po to group tracking: {group_trackings_to_po}")

  return (trackings_to_costs_map, po_to_cost_map)


def map_clusters_by_tracking(all_clusters):
  result = {}
  for cluster in all_clusters:
    for tracking in cluster.trackings:
      result[tracking] = cluster
  return result


def merge_by_trackings_tuples(clusters_by_tracking, trackings_to_cost):
  for trackings_tuple, cost in trackings_to_cost.items():
    if len(trackings_tuple) == 1:
      continue

    cluster_list = [
        clusters_by_tracking[tracking]
        for tracking in trackings_tuple
        if tracking in clusters_by_tracking
    ]

    if not cluster_list:
      continue

    # Merge all candidate clusters into the first cluster (if they're not already part of it)
    # then set all trackings to have the first cluster as their value
    first_cluster = cluster_list[0]
    for other_cluster in cluster_list[1:]:
      if not (other_cluster.trackings.issubset(first_cluster.trackings) and
              other_cluster.orders.issubset(first_cluster.orders)):
        first_cluster.merge_with(other_cluster)
    for tracking in trackings_tuple:
      clusters_by_tracking[tracking] = first_cluster


def fill_costs_new(clusters_by_tracking, trackings_to_cost, po_to_cost, args):
  for cluster in clusters_by_tracking.values():
  #  print(cluster.purchase_orders)
    # Reset the cluster if it's included in the groups
    if args.groups and cluster.group not in args.groups:
      continue
    cluster.non_reimbursed_trackings = set(cluster.trackings)
    cluster.tracked_cost = 0

  # We've already merged by tracking tuple (if multiple trackings are counted as the same price)
  # so only use the first tracking in each tuple
  for trackings_tuple, cost in trackings_to_cost.items():
    first_tracking = trackings_tuple[0]
    if first_tracking in clusters_by_tracking:
      cluster = clusters_by_tracking[first_tracking]
      cluster.tracked_cost += cost
      for tracking in trackings_tuple:
        if tracking in cluster.non_reimbursed_trackings:
          cluster.non_reimbursed_trackings.remove(tracking)

  # Next, manual PO fixes
  for cluster in clusters_by_tracking.values():
    pos = cluster.purchase_orders
    if pos:
      for po in pos:
        cluster.tracked_cost += float(po_to_cost.get(po, 0.0))
       #print(po)


def fill_cancellations(all_clusters, config):
  retriever = CancelledItemsRetriever(config)
  cancellations_by_order = retriever.get_cancelled_items()

  for cluster in all_clusters:
    cluster.cancelled_items = []
    for order in cluster.orders:
      if order in cancellations_by_order:
        cluster.cancelled_items += cancellations_by_order[order]


def reconcile_new(config, args):
  print("New reconciliation!")
  reconciliation_uploader = ReconciliationUploader(config)

  tracking_output = TrackingOutput(config)
  trackings = tracking_output.get_existing_trackings()
  reconcilable_trackings = [t for t in trackings if t.reconcile]
  # start from scratch
  all_clusters = []
  clusters.update_clusters(all_clusters, reconcilable_trackings)

  fill_email_ids(all_clusters, config)
  all_clusters = clusters.merge_orders(all_clusters)
  fill_costs(all_clusters, config)

  # add manual PO entries (and only manual ones)
  reconciliation_uploader.override_pos_and_costs(all_clusters)

  driver_creator = DriverCreator()
  group_site_manager = GroupSiteManager(config, driver_creator)

  trackings_to_cost, po_to_cost = get_new_tracking_pos_costs_maps(
      config, group_site_manager, args)

 # print(f"trackings: {trackings_to_cost}")
  #print(f"pos: {po_to_cost}")


  clusters_by_tracking = map_clusters_by_tracking(all_clusters)

 #tracking_to_po, po_to_cost = _get_usa_tracking_pos_costs_maps(self)
  #fill_purchase_orders(all_clusters, tracking_to_po, args)

  merge_by_trackings_tuples(clusters_by_tracking, trackings_to_cost)

  fill_costs_new(clusters_by_tracking, trackings_to_cost, po_to_cost, args)

  fill_cancellations(all_clusters, config)
 # print(all_clusters)
  trackings_to_po = get_usa_purchase_orders(config, driver_creator)
  fill_purchase_orders(all_clusters, trackings_to_po, args)
  reconciliation_uploader.download_upload_clusters_new(all_clusters)


def main():
  parser = argparse.ArgumentParser(description='Reconciliation script')
  parser.add_argument("--groups", nargs="*")
  args, _ = parser.parse_known_args()

  print(f"args: {args.groups}")

  with open(CONFIG_FILE, 'r') as config_file_stream:
    config = yaml.safe_load(config_file_stream)

  reconcile_new(config, args)

def fill_purchase_orders(all_clusters, tracking_to_po, args):
  print("Filling purchase orders")

  for cluster in all_clusters:
    if args.groups and cluster.group not in args.groups:
      continue

    #cluster.non_reimbursed_trackings = set(cluster.trackings)
    for tracking in cluster.trackings:
      if tracking in tracking_to_po:
        cluster.purchase_orders.add(tracking_to_po[tracking])
        #cluster.non_reimbursed_trackings.remove(tracking)

def get_usa_purchase_orders(config, driver_creator):
    print("Getting USA POs")
    result = {}
    trackings_to_cost={}
    po_to_cost ={}
    driver = driver_creator.new()
    driver.get("https://usabuying.group/login")
    group_config = config['groups']['usa']
    driver.find_element_by_name("credentials").send_keys(
        group_config['username'])
    driver.find_element_by_name("password").send_keys(group_config['password'])
    # for some reason there's an invalid login button in either the first or second array spot (randomly)
    for element in driver.find_elements_by_name("log-me-in"):
      try:
        element.click()
      except:
        pass
    time.sleep(2)
    try:
      with tqdm(desc='Fetching USA check-ins', unit='page') as pbar:
        # Tell the USA tracking search to find received tracking numbers from the beginning of time
        driver.get("https://usabuying.group/trackings")
        time.sleep(3)
        date_filter_div = driver.find_element_by_class_name(
            "reports-dates-filter-cnt")
        date_filter_btn = date_filter_div.find_element_by_tag_name("button")
        date_filter_btn.click()
        time.sleep(1)

        date_filter_div.find_element_by_xpath(
            '//a[contains(text(), "None")]').click()
        time.sleep(2)

        status_dropdown = driver.find_element_by_name("filterPurchaseid")
        status_dropdown.click()
        time.sleep(1)

        status_dropdown.find_element_by_xpath("//*[text()='Received']").click()
        time.sleep(1)

        driver.find_element_by_xpath(
            "//i[contains(@class, 'fa-search')]").click()
        time.sleep(4)
        driver.find_element_by_class_name('react-bs-table-pagination').find_element_by_tag_name('button').click()
        driver.find_element_by_css_selector("a[data-page='100']").click()


        while True:
          time.sleep(4)
          table = driver.find_element_by_class_name("react-bs-container-body")
          rows = table.find_elements_by_tag_name('tr')
          for row in rows:
            entries = row.find_elements_by_tag_name('td')
            tracking = entries[2].text
            purchase_order = entries[3].text.split(' ')[0]
            result[tracking] = purchase_order

          pbar.update()
          next_page_button = driver.find_elements_by_xpath(
              "//li[contains(@title, 'next page')]")
          if next_page_button:
            next_page_button[0].find_element_by_tag_name('a').click()
          else:
            break
      return result
    finally:
      driver.close()

if __name__ == "__main__":
  main()      